import logging
import argparse
import requests
import json
import socket
import time
import os
import hashlib
import queue
import sys
from threading import Thread
from enum import Enum


class MessageType(Enum):
    HELLO_REQUEST = 1
    HELLO_RESPONSE = 2
    PIECE_REQUEST = 3
    PEICE_RESPONSE = 4
    ERROR = 5

def message_to_bytes(type, data=b"", version=0x01):
    return version.to_bytes(1, "big") + type.value.to_bytes(1, "big") + len(data).to_bytes(2, "big") + data


# function to parse the wanted torrent file
def parse_torrent_file(file):
    with open("./torrents/" + file, "r") as f:
        torrent_data = json.load(f)
    return torrent_data['torrent_id'], torrent_data['tracker_url'], torrent_data['file_size'], torrent_data['piece_size'], torrent_data['pieces'], torrent_data['file_name']


# function to get ip address of this machine
def get_private_ip():
    h_name = socket.gethostname()
    return socket.gethostbyname(h_name)


# function to get a list of peers
def get_peer_list(tracker_url, peer_id, ip, port, torrent_id, peer_q):
    global peer_list 
    peer_list = []
    interval = 0
    while True:
        params = {
        'peer_id': "-ECEN426-" + peer_id,
        'ip': ip,
        'port': port,
        'torrent_id': torrent_id
        }
        response = requests.get(tracker_url, params=params)
        logging.info(f"Request is: {response.url}")
        logging.info(f"Response is: {response.text}")
        if response.status_code == 200:
            payload = response.json()
            for peer in payload['peers']:
                if not peer in peer_list:
                    peer_list.append(peer)
                    peer_q.put(peer)
            interval = payload['interval']
        time.sleep(interval)
    
    

def start_nibble_torrent_requests(socket, torrent_id, piece_q, dest, peer):
    send_hello(socket, torrent_id)
    hello_data = receive_data(socket)
    boolean_pieces_list = get_boolean_list_from_hello(hello_data)
    logging.info("Start sending/receiving pieces")
    send_recv_piece(socket, boolean_pieces_list, piece_q, dest, peer)
    logging.info("about done receiving data")
    


def send_recv_piece(socket, boolean_pieces_list, piece_q, dest, peer):
    while True:
        if piece_q.empty(): break
        piece = piece_q.get()
        if not boolean_pieces_list[piece[0]]: 
            piece_q.put(piece)
            continue
        byte_size = max(1, (piece[0].bit_length() + 7) // 8)
        logging.info(f"Piece number: {piece[0]}")
        data = piece[0].to_bytes(byte_size, "big")
        message = message_to_bytes(MessageType.PIECE_REQUEST, piece[0].to_bytes(byte_size, "big"))
        try:
            socket.sendall(message)
        except BrokenPipeError:
            logging.info("Peer disconnected. Move on to another peer.")
            peer_list.remove(peer)
            piece_q.put(piece)
            piece_q.task_done()
            break
        data = receive_data(socket)
        if data == None:
            logging.info("Bad recv. Putting piece back to queue.")
            piece_q.put(piece)
            piece_q.task_done()
            break
        if data == MessageType.ERROR:
            piece_q.put(piece)
            piece_q.task_done()
            continue
        if not verify_data(data, piece[1]):
            logging.info("Bad data. Putting piece back to queue.")
            piece_q.put(piece)
            piece_q.task_done()
            continue
        write_data_to_file(data, piece[0], dest)
        piece_q.task_done()


def write_data_to_file(data, index, dest):
    with open(f"{dest}/{index}", 'wb') as file:
        file.write(data)


def verify_data(data, piece):
    hasher = hashlib.sha1()
    hasher.update(data)
    hashed_result = hasher.hexdigest()
    return piece == hashed_result


def get_boolean_list_from_hello(hello_data):
    pieces_boolean_list = []
    for byte in hello_data:
        for i in range(7, -1, -1):
            pieces_boolean_list.append((byte >> i) & 1)
    return pieces_boolean_list


def send_hello(socket, torrent_id):
    message = message_to_bytes(MessageType.HELLO_REQUEST, bytes.fromhex(torrent_id))
    socket.sendall(message)


def receive_data(socket):
    header = b''
    while len(header) < 4:
        data = socket.recv(4 - len(header))
        if not data: return None
        header += data
    message_type = header[1:2]
    if int.from_bytes(message_type, "big") == MessageType.ERROR: return MessageType.ERROR
    length = int.from_bytes(header[2:], "big")
    if length < 4096: logging.info(f"Received too little: {length}")
    if length > 4096: logging.info(f"Received too much: {length}")

    peice_data = b''
    while len(peice_data) < length:
        data = socket.recv(length - len(peice_data))
        if not data: return None
        peice_data += data
    return data


# function to connect to a peer
def connect_to_peer(peer_q, torrent_id, netid, piece_q, dest, thread_number):
    while True:
        logging.info(f"Working on thread number {thread_number}")
        peer = peer_q.get()
        if netid in peer[1]: 
            continue
        peer_ip, peer_port = peer[0].split(':')
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((peer_ip, int(peer_port)))
            logging.info(f"Connected to peer at {peer_ip}:{peer_port}")
            start_nibble_torrent_requests(sock, torrent_id, piece_q, dest, peer)
        except ConnectionRefusedError:
            logging.info(f"Failed to connect to peer at {peer_ip}:{peer_port}")
    

def tracker(tracker_url, netid, port, torrent_id, peer_q):
    Thread(target=get_peer_list, args=[tracker_url, netid, get_private_ip(), port, torrent_id, peer_q]).start()


def downloader(torrent_id, peer_q, netid, piece_q, dest):
    threads = []
    try:
        for i in range(5):
            t = Thread(target=connect_to_peer, daemon=True, args=[peer_q, torrent_id, netid, piece_q, dest, i + 1])
            t.start()
            threads.append(t)
    except KeyboardInterrupt:
        logging.info("Keyboard Interrupt Detected. Exiting...")
        for i in range(5):
            peer_q.put(None)
        for t in threads:
            t.join()
        sys.exit(0)


def create_destination_folder(dest):
    if not os.path.exists(dest):
        os.makedirs(dest)


def create_piece_queue(pieces):
    piece_q = queue.Queue()
    for pair in enumerate(pieces):
        piece_q.put(pair)
    return piece_q


def stitch_file_worker(piece_q, dest, num_pieces, file_name):
    piece_q.join()
    logging.info("Writing final file")
    with open(f"{dest}/{file_name}", 'wb') as dest_file:
        for i in range(num_pieces):
            with open(f"{dest}/{i}", 'rb') as partial_file:
                dest_file.write(partial_file.read())


def stitch_file(piece_q, dest, num_pieces, file_name):
    Thread(target=stitch_file_worker, daemon=True, args=[piece_q, dest, num_pieces, file_name]).start()


def send_piece_to_peer(dest, index, conn):
    with open(f"{dest}/{index}", 'rb') as file:
        message = message_to_bytes(MessageType.PEICE_RESPONSE, file.read())
        conn.sendall(message)


def create_bit_field(n):
    # Calculate the number of bytes needed to hold n 1s
    num_bytes = (n + 7) // 8  # Equivalent to ceil(n/8)

    # Create a bytearray with the required number of bytes
    bit_field = bytearray(num_bytes)

    # Set the first n bits to 1
    for i in range(n):
        byte_index = i // 8
        bit_index = i % 8
        bit_field[byte_index] |= (1 << (7 - bit_index))

    return bit_field

# start here tomorrow. first request is torrent_id, then the index
def upload_handle_client(conn, num_pieces, dest, torrent_id):
    # hello
    while True:
        request_torrent_id = receive_data(conn)
        if request_torrent_id is None: return
        if request_torrent_id == MessageType.ERROR: return
        if verify_data(torrent_id.encode(), request_torrent_id):
            logging.info("Client requested a torrent I don't seed.")
            message = message_to_bytes(MessageType.ERROR, b"I don't seed this torrent.")
            conn.sendall(message)
            return
        else: 
            logging.info("Client requested a torrent I do seed.")
            bit_field = create_bit_field(num_pieces)
            message = message_to_bytes(MessageType.HELLO_RESPONSE, bit_field)
            conn.sendall(message)
            break
    
    # pieces
    while True:
        logging.info("Sending pieces now.")
        try:
            print("recv")
            data = receive_data(conn)
            print("done recv")
        except ConnectionResetError:
            logging.info("Client disconnected...")
            break
        if not data:
            logging.info("Client disconnected...")
            break
        index = int.from_bytes(data, "big")
        logging.info(f"Uploader request index is: {index}")
        if index > num_pieces:
            message = message_to_bytes(MessageType.ERROR, b"Index of out bound.")
            conn.sendall(message)
            continue
        elif not os.path.exists(f"{dest}/{index}"):
            message = message_to_bytes(MessageType.ERROR, b"I don't have the piece.")
            conn.sendall(message)
            continue
        else:
            logging.info(f"Sending index {index} to peer.")
            send_piece_to_peer(dest, index, conn)


def uploader_worker(uploader_q, num_pieces, dest, torrent_id, thread_number):
    while True:
        conn = uploader_q.get()
        if conn is None: 
            break
        logging.info(f"Uploader thread number {thread_number} processing client...")
        upload_handle_client(conn, num_pieces, dest, torrent_id)
        logging.info(f"Uploader thread number {thread_number} is done!")

def uploader(port, uploader_q, num_pieces, dest, torrent_id):
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("", port))
    server_socket.listen()
    logging.info(f"Listening on port {port}")
    uploader_threads = []
    try:
        for i in range(5):
            t = Thread(target=uploader_worker, daemon=True, args=[uploader_q, num_pieces, dest, torrent_id, i + 1])
            t.start()
            uploader_threads.append(t)
        while True:
            conn, address = server_socket.accept()
            logging.info(f"Connection from: {address}")
            logging.info(f"Putting connection {address} into the queue...")
            uploader_q.put(conn)
    except KeyboardInterrupt:
        logging.info("Keyboard Interrupt Detected. Exiting...")
        for i in range(5):
            uploader_q.put(None)
        for t in uploader_threads:
            t.join()
        sys.exit(0)

def run(port, dest, netid, torrent_file):
    torrent_id, tracker_url, file_size, piece_size, pieces, file_name = parse_torrent_file(torrent_file)
    peer_q = queue.Queue()
    piece_q = create_piece_queue(pieces)
    uploader_q = queue.Queue()
    tracker(tracker_url, netid, port, torrent_id, peer_q)
    downloader(torrent_id, peer_q, netid, piece_q, dest)
    stitch_file(piece_q, dest, len(pieces), file_name)
    uploader(port, uploader_q, len(pieces), dest, torrent_id)


# function to parse arguments
def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "netid",
        type=str,
        help="Your NetID",
    )
    parser.add_argument(
        "torrent_file",
        type=str,
        choices=["byu.png.ntorrent", "dQw4w9WgXcQ.mp4.ntorrent", "problem.gif.ntorrent", "programming.jpg.ntorrent", "s0csx3lou9941.jpeg.ntorrent", "s56uf5sn43b81.png.ntorrent"],
        help="The torrent file for the file you want to download.",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        required=False,
        default=8088,
        help="The port to receive peer connections from.",
    )
    parser.add_argument(
        "-d",
        "--dest",
        type=str,
        required=False,
        default="./dest",
        help="The folder to download to and seed from.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        required=False,
        action="store_true",
        help="Turn on debugging messages.",
    )
    return parser.parse_args()

# main function
if __name__ == "__main__":
    args = parse_arguments()
    create_destination_folder(args.dest)
    # if verbose flag is high, turn on verbose
    if args.verbose:
        logging.basicConfig(format="%(levelname)s:%(message)s", level=logging.DEBUG)
    try:
        run(args.port, args.dest, args.netid, args.torrent_file) 
    except KeyboardInterrupt:
        logging.info("Keyboard Interrupt Detected. Exiting...")
        sys.exit(0)
