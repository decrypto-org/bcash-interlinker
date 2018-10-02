from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
import math
from tqdm import tqdm
import configparser

from merkle import mtr

config = configparser.ConfigParser()
config.read('config.ini')

rpc_connection = AuthServiceProxy("http://%s:%s@%s:%s" %
        (config['daemon']['user'], config['daemon']['password'],
            config['daemon']['host'], config['daemon']['port']))

STARTING_BLOCK = config['fork']['startingblock']
MAX_TARGET = int(config['nipopows']['maxtarget'], 16)

def level(block_id, target):
    return -int(math.ceil(math.log(float(block_id) / target, 2)))

class Block:
    def __init__(self, header):
        self.id = bytes.fromhex(header['hash'])[::-1] # internal byte order
        self.level = level(int(header['hash'], 16), MAX_TARGET)

    def __repr__(self):
        return '<Block%s>' % {'id': self.id, 'level': self.level}

class BlockNotFound(Exception):
    pass

def get_block_header(blk):
    BLOCK_NOT_FOUND_ERROR_CODE = -5
    try:
        return rpc_connection.getblockheader(blk)
    except JSONRPCException as err:
        if err.code == BLOCK_NOT_FOUND_ERROR_CODE:
            raise BlockNotFound(blk)
        else:
            raise

def blocks_between(from_block, to_block=None):
    from_block = get_block_header(from_block)
    if to_block is not None:
        to_block = get_block_header(to_block)

    block = from_block
    while block != to_block:
        yield Block(block)
        if 'nextblockhash' not in block:
            break
        block = get_block_header(block['nextblockhash'])

    if to_block is not None:
        yield Block(to_block)


def interlink(best_block):
    interlink = []
    for blk in tqdm(blocks_between(STARTING_BLOCK, best_block)):
        interlink[:blk.level + 1] = [blk.id] * (blk.level + 1)
    return interlink

def get_best_block_hash():
    return rpc_connection.getbestblockhash()

def send_velvet_tx(payload_buf):
    from bitcoin.core import CMutableTxOut, CScript, CMutableTransaction, OP_RETURN
    VELVET_FORK_MARKER = b'interlink'
    digest_outs = [CMutableTxOut(0, CScript([OP_RETURN, VELVET_FORK_MARKER, payload_buf]))]
    tx = CMutableTransaction([], digest_outs)

    change_address = rpc_connection.getaccountaddress("")
    funded_raw_tx = rpc_connection.fundrawtransaction(tx.serialize().hex(),
            {'changeAddress': change_address})['hex']
    signed_funded_raw_tx = rpc_connection.signrawtransaction(funded_raw_tx)['hex']
    return rpc_connection.sendrawtransaction(signed_funded_raw_tx)

if __name__ == '__main__':
    from time import sleep

    last_block_hash = '0' * 64
    while True:
        cur_block_hash = get_best_block_hash()
        if cur_block_hash != last_block_hash:
            last_block_hash = cur_block_hash
            new_interlink = interlink(cur_block_hash)
            interlink_mtr = mtr(new_interlink)
            print('new interlink', [x[::-1].hex() for x in new_interlink])
            print('mtr hash', interlink_mtr.hex())
            print('velvet tx', send_velvet_tx(interlink_mtr))

        sleep(1) # second
