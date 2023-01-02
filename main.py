import ssl
import json
import yaml
import aiohttp
import asyncio
import logging
import aiosqlite
import contextlib
import asyncio_mqtt as aiomqtt

from base64 import b64decode
from sqlite3 import OperationalError


# Load configuration file
with open("config.yaml", "rb") as f:
    config = yaml.safe_load(f)

# MQTT ssl settings
tls_params = aiomqtt.TLSParameters(
    ca_certs=None,
    cert_reqs=ssl.CERT_REQUIRED,
    tls_version=ssl.PROTOCOL_TLS,
)


async def tts_client(app_config: dict, queue: asyncio.queues.Queue) -> None:
    mqtt_broker = app_config.get("tts_mqtt_broker", config["tts_default_mqtt_broker"])
    mqtt_port = app_config.get("tts_mqtt_port", config["tts_default_mqtt_port"])

    while True:
        try:
            async with aiomqtt.Client(
                hostname=mqtt_broker,
                port=mqtt_port,
                username=app_config["tts_username"],
                password=app_config["tts_apikey"],
                tls_params=tls_params,
            ) as client:
                logging.info(
                    f"connected to tts application {app_config['tts_username']}"
                )
                async with client.messages() as messages:
                    await client.subscribe(
                        app_config.get("tts_topic", "v3/+/devices/+/up")
                    )
                    async for message in messages:
                        asyncio.create_task(
                            publish_to_thingsboard(message, app_config, queue)
                        )
        except aiomqtt.MqttError as error:
            logging.error(
                f"{error}. Reconnecting in {config['tts_reconnect_interval']} seconds to {mqtt_broker} application {app_config['tts_username']}."
            )
            await asyncio.sleep(config["tts_reconnect_interval"])


async def provision_device_on_thingsboard(dev_eui: str, app_config: dict) -> str:
    logging.info(
        f"provision new device {dev_eui} from application {app_config['tts_username']}"
    )
    provision_request = {
        "deviceName": dev_eui,
        "provisionDeviceKey": app_config["tb_provision_device_key"],
        "provisionDeviceSecret": app_config["tb_provision_device_secret"],
    }

    access_token = ""
    async with aiohttp.ClientSession() as session:
        url = f"{config['tb_url']}/api/v1/provision"
        async with session.post(url, data=json.dumps(provision_request)) as resp:
            body = await resp.text()
            json_body = json.loads(body)

            if json_body.get("status") == "SUCCESS":
                access_token = json_body.get("credentialsValue")
            else:
                logging.error(f"{json_body.get('errorMsg')} {dev_eui}")

    return access_token


def get_telemetry(data: dict) -> dict:
    telemetry = {}
    uplink_message = data["uplink_message"]

    # Add decoded payload
    # Prefer normalized payload if present in uplink_message
    if "normalized_payload" in uplink_message:
        payload = uplink_message["normalized_payload"][0]
        for prop in payload:
            for meassurement in payload[prop]:
                telemetry[f"{prop.lower()}{meassurement.title()}"] = payload[prop][
                    meassurement
                ]
    elif "decoded_payload" in uplink_message:
        telemetry = uplink_message["decoded_payload"]

    # Frame port
    if "f_port" in uplink_message:
        telemetry["framePort"] = uplink_message["f_port"]
    else:
        telemetry["framePort"] = 0

    # Raw payload in HEX
    if "frm_payload" in uplink_message:
        telemetry["rawPayload"] = b64decode(uplink_message["frm_payload"]).hex().upper()

    telemetry["frameCount"] = uplink_message["f_cnt"]
    telemetry["rssi"] = uplink_message["rx_metadata"][0]["rssi"]
    telemetry["snr"] = uplink_message["rx_metadata"][0]["snr"]
    telemetry["spreadingFactor"] = uplink_message["settings"]["data_rate"]["lora"][
        "spreading_factor"
    ]

    return telemetry


async def publish_to_thingsboard(
    message: aiomqtt.client.Message, app_config: dict, queue: asyncio.queues.Queue
) -> None:
    payload = message.payload

    data = json.loads(payload.decode("utf-8"))
    dev_eui = data["end_device_ids"]["dev_eui"]

    logging.info(
        f"received new payload from device {dev_eui} application {app_config['tts_username']}"
    )

    telemetry = get_telemetry(data)

    db = await aiosqlite.connect(config["tb_secrets_db"])
    cursor = await db.execute(
        f"SELECT tb_access_token FROM thingsboard WHERE device_eui='{dev_eui}'"
    )

    row = await cursor.fetchone()
    if row is None:
        access_token = await provision_device_on_thingsboard(dev_eui, app_config)
        if access_token == "":
            # TODO: Failed to cancel task
            return None

        await db.execute(
            f"INSERT INTO thingsboard (device_eui, tb_access_token) VALUES ('{dev_eui}', '{access_token}')"
        )
        await db.commit()
    else:
        access_token = row[0]

    await cursor.close()
    await db.close()

    async with aiohttp.ClientSession() as session:
        # Publish telemetry
        await queue.put(
            {"telemetry": telemetry, "dev_eui": dev_eui, "access_token": access_token}
        )

        # Publish attributes if device was provisioned
        if row is None:
            attributes = {
                "deviceId": data["end_device_ids"]["device_id"],
                "applicationId": data["end_device_ids"]["application_ids"][
                    "application_id"
                ],
            }
            await queue.put(
                {
                    "attributes": attributes,
                    "dev_eui": dev_eui,
                    "access_token": access_token,
                }
            )


async def thingsboard_publisher(queue: asyncio.queues.Queue) -> None:
    async with aiohttp.ClientSession() as session:
        while True:
            request = await queue.get()
            try:
                if "telemetry" in request:
                    logging.info(
                        f"publish telemetry to thingsboard device {request['dev_eui']}"
                    )
                    url = (
                        f"{config['tb_url']}/api/v1/{request['access_token']}/telemetry"
                    )
                    await session.post(url, json=request["telemetry"])
                if "attributes" in request:
                    logging.info(
                        f"publish attributes to thingsboard device {request['dev_eui']}"
                    )
                    url = f"{config['tb_url']}/api/v1/{request['access_token']}/attributes"
                    await session.post(url, json=request["attributes"])
            except aiohttp.ClientError as e:
                logging.error(f"Error processing publish {request}: {e}")

            queue.task_done()


async def cancel_tasks(tasks: set) -> None:
    logging.info("Cancel running tasks")
    for task in tasks:
        if task.done():
            continue
        try:
            task.cancel()
            await task
        except asyncio.CancelledError:
            pass


async def main() -> None:
    # ThingsBoard publisher queue
    queue = asyncio.Queue()

    try:
        async with aiosqlite.connect(config["tb_secrets_db"]) as db:
            await db.execute(
                "CREATE TABLE thingsboard (device_eui VARCHAR(16), tb_access_token VARCHAR(50), created TIMESTAMP)"
            )
            await db.execute(
                "CREATE UNIQUE INDEX idx_device_eui ON thingsboard (device_eui)"
            )
            await db.commit()
    except OperationalError:
        pass

    async with contextlib.AsyncExitStack() as stack:
        # Keep track of the asyncio tasks that we create, so that
        # we can cancel them on exit
        clients = set()
        stack.push_async_callback(cancel_tasks, clients)

        # Connect to TTS applications
        for app_config in config["tts_applications"]:
            client = asyncio.create_task(tts_client(app_config, queue))
            clients.add(client)

        # Start ThingsBoard publisher task
        publisher = asyncio.create_task(thingsboard_publisher(queue))
        clients.add(publisher)

        await asyncio.gather(*clients)


if __name__ == "__main__":
    try:
        logging.basicConfig(level=logging.INFO)
        asyncio.run(main())
    except KeyboardInterrupt:
        exit(0)
