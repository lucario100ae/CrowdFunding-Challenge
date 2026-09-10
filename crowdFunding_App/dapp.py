import logging
from os import environ
import json
import requests
import binascii

logging.basicConfig(level="INFO")
logger = logging.getLogger(__name__)

rollup_server = environ["ROLLUP_HTTP_SERVER_URL"]
logger.info(f"HTTP rollup_server URL is {rollup_server}")

# GUARDAR CAMPANHAS 
campaigns = {}
campaign_counter = 0


##########################################################################
# FUNÇOES JA DECLARADAS NOS TUTORIAIS
def string_to_hex(s: str) -> str:
    return "0x" + binascii.hexlify(s.encode("utf-8")).decode()


def hex_to_string(hexstr: str) -> str:
    if not isinstance(hexstr, str):
        return ""
    if hexstr.startswith("0x"):
        hexstr = hexstr[2:]
    if hexstr == "":
        return ""
    try:
        return binascii.unhexlify(hexstr).decode("utf-8")
    except UnicodeDecodeError:
        return "0x" + hexstr

    
def send_notice(payload):
    json_string = json.dumps(payload)
    hex_payload = string_to_hex(json_string)

    try:
        response = requests.post(
            f"{rollup_server}/notice",
            json={"payload": hex_payload},
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        logger.info(f"notice → status {response.status_code}")
    except requests.RequestException as error:
        logger.error("Error emitting notice: %s", error)


def structure_voucher(function_signature, destination, types, values, value=0) -> dict:
    selector = function_signature_to_4byte_selector(function_signature)
    encoded_args = encode(types, values)
    payload = "0x" + (selector + encoded_args).hex()

    return {
        "destination": destination,
        "payload": payload
    }


def emitVoucher(voucher: dict):
    try:
        response = requests.post(
            f"{rollup_server}/voucher",
            json= voucher,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        logger.info(f"emit_voucher → status {response.status_code}")
    except requests.RequestException as error:
        logger.error("Error emitting voucher: %s", error)
##########################################################################################


def handle_advance(data):
    global campaign_counter    # PASSAR CONTADOR PRA FUNÇAO


    logger.info(f"Recebido advance request: {data}")
    sender = data["metadata"]["msg_sender"]
    payload_raw = bytes.fromhex(data["payload"][2:]).decode("utf-8")
    
    try:
        input_terminal = json.loads(payload_raw)
        action = input_terminal.get("action")

        # CRIAR CAMPANHA
        if str(action) == "1":
            goal = int(input_terminal.get("goal", 0))
            if goal <= 0:
                raise ValueError("A meta da campanha deve ser maior que zero.")

            campaign_counter += 1
            campaign_id = campaign_counter

            campaigns[campaign_id] = {
                "creator": sender,
                "goal": goal,
                "received": 0,
                "completed": False
            }

            notice_data = {
                "event": "CampaignCreated",
                "campaign_id": campaign_id,
                "creator": sender,
                "goal": goal
            }
            send_notice(notice_data)
            logger.info("CAMPANHA CRIADA")
            return "accept"

        # INVESTIR EM UMA CAMPANHA
        elif str(action) == "2":
            campaign_id = int(input_terminal.get("campaign_id"))
            amount = int(input_terminal.get("amount", 0))

            if campaign_id not in campaigns:
                raise ValueError("Campanha não encontrada.")

            campaign = campaigns[campaign_id]

            # CONFERIR SE O É VIAVEL O INVESTIMENTO
            if campaign["completed"]:
                raise ValueError("Meta já alcançada.")
            if amount <= 0:
                raise ValueError("Valor do investimento deve ser maior que zero.")
            
            campaign["received"] += amount


            # AVISO DE INVESTIMENTO RECEBIDO
            send_notice({
                "event": "InvestmentReceived",
                "campaign_id": campaign_id,
                "investor": sender,
                "amount": amount,
                "total_received": campaign["received"]
            })


            # VERIFICAR SE A META FOI ALCANÇADA
            if campaign["received"] >= campaign["goal"]:
                campaign["completed"] = True
                

                
                # NOTICE CONFIRMANDO SE META BATIDA
                logger.info("META BATIDA, ENVIANDO NOTICE")
                send_notice({
                    "event": "GoalReached",
                    "campaign_id": campaign_id,
                    "total_received": campaign["received"],
                    "status": "Target reached successfully"
                })

            return "accept"


        else:
            logger.error("Ação desconhecida.")
            return "reject"


    except Exception as e:
        logger.error(f"Erro ao processar entrada: {e}")
        return "reject"


def handle_inspect(data):
    logger.info(f"Recebido inspect request: {data}")
    payload_hex = "0x" + json.dumps(campaigns).encode("utf-8").hex()
    requests.post(rollup_server + "/report", json={"payload": payload_hex})
    return "accept"

handlers = {
    "advance_state": handle_advance,
    "inspect_state": handle_inspect,
}

finish = {"status": "accept"}

while True:
    logger.info("Sending finish")
    response = requests.post(rollup_server + "/finish", json=finish)
    logger.info(f"Received finish status {response.status_code}")
    if response.status_code == 202:
        logger.info("No pending rollup request, trying again")
    else:
        rollup_request = response.json()
        data = rollup_request["data"]
        handler = handlers[rollup_request["request_type"]]
        finish["status"] = handler(rollup_request["data"])
