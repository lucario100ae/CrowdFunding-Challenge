import logging
from os import environ
import json
import requests
import binascii
from datetime import datetime, date
from eth_utils import function_signature_to_4byte_selector
from eth_abi import encode
from eth_abi import decode

logging.basicConfig(level="INFO")
logger = logging.getLogger(__name__)

rollup_server = environ["ROLLUP_HTTP_SERVER_URL"]
logger.info(f"HTTP rollup_server URL is {rollup_server}")

ERC20_PORTAL = "0x9C21AE12590ca1E912f293b21C43D8c115456F91"
ALLOWED_ERC20 = "0x123euNaoFacoIdeiaDoQueEuToFazendoAqui123" # Token hipotetico

# ########################################################################
# DEFININDO AS CLASSES CAMPANHA E CAMPANARIO (kkkkkkkk)
class Campanha:
    def __init__(self ,nome_campanha:str ,creator:str ,data ,goal:int, token_address ): # Por nao saber o tipo da biblioteca datatime, optei por nao tipar a data final
        self.name = nome_campanha
        self.creator = creator 
        self.final_data = data 
        self.goal= goal
        self.receive = 0
        self.completed = False
        self.token_address = token_address

    # 1. Investir na campanha
    def investir(self,amount:int,token_address):
        # confere o token
        if token_address != self.token_address:
            logger.warning("Token não aceito na campanha.")
            return False

        if self.completed:
            logger.info("Campanha ja encerrada.")
            return False
        
        if amount <= 0:
            logger.warning("O valor do investimento deve ser maior que zero.")
            return False
        
        self.receive += amount
        if self.receive >= self.goal:
            self.completed = True
        return True


class Campanario:
    def __init__(self):
        self.campanhas: list[Campanha] = []

    # 1. Adicionar nova campanha
    def adicionar(self, campanha: Campanha):
        self.campanhas.append(campanha)

    # 2. Listar todas
    def listar_todas(self):
        return self.campanhas

    # 3. Buscar uma campanha pelo nome
    def buscar_por_nome(self, nome: str):
        for campanha in self.campanhas:
            if campanha.name.lower() == nome.lower():
                return campanha
        return None

    # 4. Realizar um investimento buscando a campanha pelo nome
    def investir_em_campanha(self, nome: str, valor: int):
        campanha = self.buscar_por_nome(nome)
        if campanha:
            hoje = date.today()
            if campanha.final_data >= hoje:
                campanha.investir(valor)
                return True
        return False

    # 5. Criar campanha pelo campanario
    def criar_campanha(self, nome_campanha, creator, data_texto, goal, token):

        # Função interna para validar e converter a data (acabei de descobrir q isso é possivel)
        def data_valida(texto, formato="%d/%m/%Y"):
            try:
                data_informada = datetime.strptime(texto, formato).date()
                hoje = date.today()
                if data_informada > hoje:
                    return data_informada 
                return False
            except ValueError:
                return False

        # 1. Valida se a campanha já existe pelo nome
        if (self.buscar_por_nome(nome_campanha) is not None):
            logger.warning("Erro: Já existe uma campanha com o nome '%s'.", nome_campanha)
            return False   # Encerra o metodo

        # 2. Valida o formato e se a data é futura
        data_convertida = data_valida(data_texto)
        if not data_convertida:
            logger.warning("Erro: A data '%s' é inválida ou não é uma data futura no formato DD/MM/AAAA.", data_texto)
            return False   # Encerra o metodo

        # 3. Cria e guarda a campanha
        nova_campanha = Campanha(nome_campanha, creator, data_convertida, goal,token)
        self.campanhas.append(nova_campanha)
        logger.info("Campanha '%s' criada com sucesso!", nome_campanha)
        return True

    def remover(self,campanha):
        try:
            self.campanhas.remove(campanha)
            return True
        except:
            return False

        


##########################################################################
# FUNÇÕES AUXILIARES DE NOTICES E VOUCHERS
######################################################################

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
campanhas = Campanario()

def handle_advance(data):
    logger.info(f"Recebido advance request: {data}")
    sender = data["metadata"]["msg_sender"]
    payload_hex = data["payload"][2:]
    payload_bytes = bytes.fromhex(payload_hex)

    try:
        input_terminal = json.loads(payload_hex)
        action = input_terminal.get("action")


        if sender == ERC20_PORTAL: # Confere se esta tratando de dinheiro >:D
            
            # INVESTIR EM UMA CAMPANHA
            if str(action) == "2":
                token, amount, = decode(["address", "address", "uint256"], payload_bytes)
 
                nome = int(input_terminal.get("nome"))
                amount = int(input_terminal.get("amount", 0))


                campaign = campanhas.buscar_por_nome(nome)
                confere = campaign.investir(amount,token)
                if not confere:
                    return "reject"

                # AVISO DE INVESTIMENTO RECEBIDO
                send_notice({
                    "event": "InvestmentReceived",
                    "campaign_name": campaign.name,
                    "investor": sender,
                    "amount": amount,
                    "total_received": campaign.receive
                })


                # VERIFICAR SE A META FOI ALCANÇADA
                if campaign.completed:

                    # NOTICE CONFIRMANDO SE META BATIDA
                    logger.info("META BATIDA, ENVIANDO NOTICE")
                    send_notice({
                        "event": "GoalReached",
                        "name": nome,
                        "total_received": campaign.receive,
                        "status": "Target reached successfully"})

                    # VOUCHER PRO DONO DA CAMPANHA
                    voucher = structure_voucher(
                            function_signature="transfer(address,uint256)",
                            destination=campaign.token_address,
                            types=["address", "uint256"],
                            values=[campaign.creator, campaign.receive])
                    emitVoucher(voucher)

                    campanhas.remover(campaign)

                return "accept"
            
            

            
        else:
            # CRIAR CAMPANHA
            if str(action) == "1":
                data_final = input_terminal.get("data",0)            
                goal = int(input_terminal.get("goal", 0))
                nome = str(input_terminal.get("name"))
                token_address = input_terminal.get("token", ALLOWED_ERC20)

                if goal <= 0:
                    raise ValueError("A meta da campanha deve ser maior que zero.")

                campanhas.criar_campanha(nome,sender,data_final,goal,token_address)


                notice_data = {"event": "CampaignCreated",
                    "campaign_name": nome,
                    "creator": sender,}

                send_notice(notice_data)
                logger.info("CAMPANHA CRIADA")
                return "accept"


            # Açao diferente de criar campanha
            else:
                logger.error("Ação desconhecida.")
                return "reject"


    except Exception as e:
        logger.error(f"Erro ao processar entrada: {e}")
        return "reject"


def handle_inspect(data):
    # Permite consultar o estado das campanhas sem alterar o estado
    logger.info(f"Recebido inspect request: {data}")
    payload_hex = "0x" + json.dumps(campanhas.listar_todas()).encode("utf-8").hex()
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