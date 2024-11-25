import socket
import threading
import zlib
import time
import os

# Message Types
MSG_DEFAULT = 0
MSG_SYN = 1
MSG_SYN_ACK = 2
MSG_ACK = 3
MSG_FIN = 4
MSG_KEEP_ALIVE = 5
MSG_FRAGMENT = 6
MSG_LAST_FRAGMENT = 7
MSG_FILE_INFO = 8
MSG_FILE_FRAGMENT = 9
MSG_FILE_LAST_FRAGMENT = 10
MSG_FRAGMENT_NAK = 12

def create_message(msg_type, sequence_number, data=b''):
    crc = zlib.crc32(data)
    crc_bytes = crc.to_bytes(4, 'big')
    sequence_bytes = sequence_number.to_bytes(4, 'big')
    return bytes([msg_type]) + sequence_bytes + crc_bytes + data

def parse_message_with_sequence(message):
    msg_type = message[0]
    sequence_number = int.from_bytes(message[1:5], 'big')
    received_crc = int.from_bytes(message[5:9], 'big')
    data = message[9:]
    crc_matched = (zlib.crc32(data) == received_crc)
    return msg_type, data, sequence_number, crc_matched

def keep_alive(sock, addr, stop_event, lost_connection_event, display_keep_alive, interval=5):
    while not stop_event.is_set():
        time.sleep(interval)
        sock.sendto(create_message(MSG_KEEP_ALIVE, 0), addr)
        if display_keep_alive:
            print(f"Sending keep-alive packet to {addr}")
        if lost_connection_event.is_set():
            stop_event.set()
            break

def receive_messages(sock, stop_event, lost_connection_event, addr, save_directory, display_keep_alive, acknowledged_sequences, nacknowledged_sequences, ack_condition, interval=5, buffer_size=2048):
    last_activity = time.time()
    message_buffers = {}

    while not stop_event.is_set():
        try:
            sock.settimeout(interval)
            data, _ = sock.recvfrom(buffer_size)
            if data:
                msg_type, msg_data, sequence_number, crc_matched = parse_message_with_sequence(data)
                if not crc_matched:
                    nack_message = create_message(MSG_FRAGMENT_NAK, sequence_number)
                    sock.sendto(nack_message, addr)
                    print(f"\nSent NAK for sequence number {sequence_number} due to CRC mismatch")
                    continue

                if msg_type == MSG_FIN:
                    print("\nPeer has closed the connection.")
                    stop_event.set()
                    break
                elif msg_type == MSG_KEEP_ALIVE:
                    last_activity = time.time()
                    if display_keep_alive:
                        print(f"\nReceived keep-alive packet from {addr}")
                elif msg_type == MSG_FRAGMENT_NAK:
                    last_activity = time.time()
                    nack_sequence_number = sequence_number
                    with ack_condition:
                        nacknowledged_sequences.add(nack_sequence_number)
                        ack_condition.notify_all()
                    print(f"\nReceived NAK for sequence number {nack_sequence_number}")
                elif msg_type == MSG_ACK:
                    last_activity = time.time()
                    ack_sequence_number = sequence_number
                    with ack_condition:
                        acknowledged_sequences.add(ack_sequence_number)
                        ack_condition.notify_all()
                else:
                    if msg_type == MSG_FILE_INFO:
                        last_activity = time.time()
                        file_name_length = msg_data[0]
                        file_name = msg_data[1:1+file_name_length].decode()
                        file_size = int.from_bytes(msg_data[1+file_name_length:1+file_name_length+4], 'big')
                        message_id = sequence_number >> 16
                        message_buffers[message_id] = {
                            'type': 'file',
                            'fragments': {},
                            'num_fragments_received': 0,
                            'total_size': 0,
                            'start_time': time.time(),
                            'file_name': file_name,
                            'expected_total_size': file_size,
                        }
                        print(f"\nReceiving file: {file_name}, Size: {file_size} bytes")
                        ack_message = create_message(MSG_ACK, sequence_number)
                        sock.sendto(ack_message, addr)
                        print(f"ACK sent for sequence {sequence_number}")
                    elif msg_type in (MSG_FILE_FRAGMENT, MSG_FILE_LAST_FRAGMENT, MSG_FRAGMENT, MSG_LAST_FRAGMENT):
                        last_activity = time.time()
                        message_id = sequence_number >> 16
                        fragment_number = sequence_number & 0xFFFF

                        if msg_type == MSG_FRAGMENT_NAK:
                            nack_message = create_message(MSG_FRAGMENT_NAK, sequence_number)
                            sock.sendto(nack_message, addr)
                            print(f"\nSent NAK for sequence number {sequence_number}")
                            continue

                        if message_id not in message_buffers:
                            if msg_type in (MSG_FILE_FRAGMENT, MSG_FILE_LAST_FRAGMENT):
                                print("Warning: Received file fragment before file info.")
                                continue
                            else:
                                message_buffers[message_id] = {
                                    'type': 'message',
                                    'fragments': {},
                                    'num_fragments_received': 0,
                                    'total_size': 0,
                                    'start_time': time.time(),
                                }

                        buffer = message_buffers[message_id]
                        buffer['fragments'][fragment_number] = msg_data
                        buffer['num_fragments_received'] += 1
                        buffer['total_size'] += len(msg_data)
                        ack_message = create_message(MSG_ACK, sequence_number)
                        sock.sendto(ack_message, addr)
                        print(f"ACK sent for sequence {sequence_number}")

                        if buffer['type'] == 'file':
                            if msg_type == MSG_FILE_LAST_FRAGMENT:
                                fragments = buffer['fragments']
                                ordered_fragments = [fragments[i] for i in sorted(fragments)]
                                complete_data = b''.join(ordered_fragments)
                                total_size = buffer['total_size']
                                num_fragments = buffer['num_fragments_received']
                                elapsed_time = time.time() - buffer['start_time']
                                save_path = os.path.join(save_directory, buffer['file_name'])
                                with open(save_path, 'wb') as f:
                                    f.write(complete_data)
                                print(f"\n{'-' * 50}")
                                print(f"Received file:")
                                print(f"Name: {buffer['file_name']}")
                                print(f"Size: {total_size} bytes")
                                print(f"Fragments: {num_fragments}")
                                print(f"Time: {elapsed_time:.2f}s")
                                print(f"{'-' * 50}\n")
                                del message_buffers[message_id]
                        else:
                            if msg_type == MSG_LAST_FRAGMENT:
                                fragments = buffer['fragments']
                                ordered_fragments = [fragments[i] for i in sorted(fragments)]
                                complete_message = b''.join(ordered_fragments)
                                total_size = buffer['total_size']
                                num_fragments = buffer['num_fragments_received']
                                elapsed_time = time.time() - buffer['start_time']
                                print(f"\n{'-' * 50}")
                                print(f"[Peer {addr}]")
                                print(f"Received message: {complete_message.decode()}")
                                print(f"Size: {total_size} bytes")
                                print(f"Fragments: {num_fragments}")
                                print(f"Time: {elapsed_time:.2f}s")
                                print(f"{'-' * 50}\n")
                                del message_buffers[message_id]
                    elif msg_type == MSG_DEFAULT:
                        last_activity = time.time()
                        print(f"\n{'-' * 50}")
                        print(f"[Peer {addr}] {msg_data.decode()}")
                        print(f"Received message:")
                        print(f"Size: {len(msg_data)} bytes")
                        print(f"Fragments: 1")
                        print(f"Time: 0.00s")
                        print(f"{'-' * 50}\n")
                        ack_message = create_message(MSG_ACK, sequence_number)
                        sock.sendto(ack_message, addr)
                        print(f"ACK sent for sequence {sequence_number}")
                    else:
                        print(f"\nUnknown message type: {msg_type}")
            else:
                raise Exception("No data received")

            if time.time() - last_activity > interval * 3:
                print("\nConnection lost. No Keep-Alive received after 3 intervals.")
                lost_connection_event.set()
                stop_event.set()
                break

        except socket.timeout:
            if time.time() - last_activity > interval * 3:
                print("\nConnection lost due to inactivity.")
                lost_connection_event.set()
                stop_event.set()
                break
        except Exception as e:
            print(f"\nReceiving error: {e}")
            stop_event.set()
            break

def handle_handshake_server(server_sock):
    data, addr = server_sock.recvfrom(1024)
    msg_type, _, _, _ = parse_message_with_sequence(data)
    if msg_type == MSG_SYN:
        server_sock.sendto(create_message(MSG_SYN_ACK, 0), addr)
        data, addr = server_sock.recvfrom(1024)
        msg_type, _, _, _ = parse_message_with_sequence(data)
        if msg_type == MSG_ACK:
            print(f"\nHandshake complete with client at {addr}\n{'=' * 50}\n")
            return addr
    return None

def handle_handshake_client(client_sock, server_address, max_retries=3, timeout=5):
    client_sock.settimeout(timeout)
    retries = 0
    while retries < max_retries:
        try:
            client_sock.sendto(create_message(MSG_SYN, 0), server_address)
            data, _ = client_sock.recvfrom(1024)
            msg_type, _, _, _ = parse_message_with_sequence(data)
            if msg_type == MSG_SYN_ACK:
                client_sock.sendto(create_message(MSG_ACK, 0), server_address)
                print(f"\nHandshake complete with server.\n{'=' * 50}\n")
                return True
        except socket.timeout:
            retries += 1
            print(f"Handshake attempt {retries} failed, retrying...")
    print("\nHandshake failed after maximum retries.")
    return False

def start_server(local_host='localhost', local_port=65432):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_sock:
        try:
            server_sock.bind((local_host, local_port))
            print(f"\nServer listening on {local_host}:{local_port}")

            save_directory = input("Enter directory to save received files (default '.'): ") or '.'
            if not os.path.exists(save_directory):
                os.makedirs(save_directory)

            display_keep_alive_input = input("Display keep-alive packets? (1 for yes, 0 for no): ") or '0'
            display_keep_alive = display_keep_alive_input == '1'

            simulate_fault_input = input("Simulate transmission error? (1 for yes, 0 for no): ") or '0'
            simulate_fault = simulate_fault_input == '1'

            stop_event = threading.Event()
            lost_connection_event = threading.Event()

            acknowledged_sequences = set()
            nacknowledged_sequences = set()
            ack_condition = threading.Condition()

            client_address = handle_handshake_server(server_sock)
            if client_address:
                keep_alive_thread = threading.Thread(
                    target=keep_alive,
                    args=(server_sock, client_address, stop_event, lost_connection_event, display_keep_alive),
                    daemon=True
                )
                keep_alive_thread.start()

                recv_thread = threading.Thread(
                    target=receive_messages,
                    args=(server_sock, stop_event, lost_connection_event, client_address, save_directory, display_keep_alive, acknowledged_sequences, nacknowledged_sequences, ack_condition),
                    daemon=True
                )
                recv_thread.start()

                send_thread = threading.Thread(
                    target=send_messages,
                    args=(server_sock, client_address, stop_event, acknowledged_sequences, nacknowledged_sequences, ack_condition, simulate_fault),
                    daemon=True
                )
                send_thread.start()

                recv_thread.join()
                send_thread.join()
                keep_alive_thread.join()
                print("\nServer stopped communication.")
            else:
                print("\nHandshake failed.")
        except Exception as e:
            print(f"\nServer error: {e}")

def start_client(local_host='localhost', local_port=65433, server_host='localhost', server_port=65432):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_sock:
        try:
            client_sock.bind((local_host, local_port))
            print(f"\nClient listening on {local_host}:{local_port}")

            save_directory = input("Enter directory to save received files (default '.'): ") or '.'
            if not os.path.exists(save_directory):
                os.makedirs(save_directory)

            display_keep_alive_input = input("Display keep-alive packets? (1 for yes, 0 for no): ") or '0'
            display_keep_alive = display_keep_alive_input == '1'

            simulate_fault_input = input("Simulate transmission error? (1 for yes, 0 for no): ") or '0'
            simulate_fault = simulate_fault_input == '1'

            stop_event = threading.Event()
            lost_connection_event = threading.Event()

            acknowledged_sequences = set()
            nacknowledged_sequences = set()
            ack_condition = threading.Condition()

            server_address = (server_host, server_port)

            if handle_handshake_client(client_sock, server_address):
                keep_alive_thread = threading.Thread(
                    target=keep_alive,
                    args=(client_sock, server_address, stop_event, lost_connection_event, display_keep_alive),
                    daemon=True
                )
                keep_alive_thread.start()

                recv_thread = threading.Thread(
                    target=receive_messages,
                    args=(client_sock, stop_event, lost_connection_event, server_address, save_directory, display_keep_alive, acknowledged_sequences, nacknowledged_sequences, ack_condition),
                    daemon=True
                )
                recv_thread.start()

                send_thread = threading.Thread(
                    target=send_messages,
                    args=(client_sock, server_address, stop_event, acknowledged_sequences, nacknowledged_sequences, ack_condition, simulate_fault),
                    daemon=True
                )
                send_thread.start()

                recv_thread.join()
                send_thread.join()
                keep_alive_thread.join()
                print("\nClient stopped communication.")
            else:
                print("\nHandshake failed.")
        except Exception as e:
            print(f"\nClient error: {e}")

def send_messages(sock, addr, stop_event, acknowledged_sequences, nacknowledged_sequences, ack_condition, simulate_fault):
    message_id_counter = 0
    sent_fragments = {}

    while not stop_event.is_set():
        try:
            max_data_size_input = input("\nEnter the minimal fragmentation size (bytes):\n")
            try:
                MAX_DATA_SIZE = int(max_data_size_input)
                if MAX_DATA_SIZE <= 0 or MAX_DATA_SIZE > 1463:
                    print("Fragmentation size must be a positive integer up to 1463 bytes.")
                    continue
            except ValueError:
                print("Invalid input. Please enter a positive integer.")
                continue

            message = input("Enter your message ('exit' to quit, 'file' to send a file): ")
            if message.lower() == 'exit':
                fin_packet = create_message(MSG_FIN, 0)
                sock.sendto(fin_packet, addr)
                print("\nSent FIN packet. Exiting...")
                stop_event.set()
                break
            elif message.lower() == 'file':
                file_path = input("Enter the file path to send: ")
                try:
                    with open(file_path, 'rb') as f:
                        file_data = f.read()
                    file_name = os.path.basename(file_path)
                    total_size = len(file_data)

                    message_id = message_id_counter
                    message_id_counter = (message_id_counter + 1) % 65536

                    file_name_bytes = file_name.encode()
                    file_name_length = len(file_name_bytes)
                    if file_name_length > 255:
                        print("File name is too long. Maximum length is 255 bytes.")
                        continue
                    file_size_bytes = total_size.to_bytes(4, 'big')
                    data = bytes([file_name_length]) + file_name_bytes + file_size_bytes

                    sequence_number = (message_id << 16) | 0

                    max_retries = 5
                    retry_count = 0
                    while retry_count < max_retries:
                        file_info_packet = create_message(MSG_FILE_INFO, sequence_number, data)
                        sock.sendto(file_info_packet, addr)
                        print(f"\nSent MSG_FILE_INFO for '{file_name}' (Sequence number {sequence_number})")
                        with ack_condition:
                            ack_received = ack_condition.wait_for(
                                lambda: sequence_number in acknowledged_sequences or sequence_number in nacknowledged_sequences,
                                timeout=5
                            )
                            if ack_received:
                                if sequence_number in acknowledged_sequences:
                                    print(f"ACK received for MSG_FILE_INFO (Sequence number {sequence_number})")
                                    acknowledged_sequences.remove(sequence_number)
                                    break
                                elif sequence_number in nacknowledged_sequences:
                                    print(f"NAK received for MSG_FILE_INFO (Sequence number {sequence_number}), retransmitting")
                                    nacknowledged_sequences.remove(sequence_number)
                                    retry_count += 1
                            else:
                                retry_count += 1
                                print(f"Timeout waiting for ACK/NAK for MSG_FILE_INFO, retransmitting (Attempt {retry_count}/5)")
                    else:
                        print(f"\nFailed to receive ACK/NAK for MSG_FILE_INFO after {max_retries} attempts")
                        stop_event.set()
                        break

                    fragments = [file_data[i:i+MAX_DATA_SIZE] for i in range(0, total_size, MAX_DATA_SIZE)]
                    num_fragments = len(fragments)
                    corrupt_fragment_index = num_fragments - 1 if simulate_fault else -1

                    for i, fragment in enumerate(fragments):
                        if i == num_fragments - 1:
                            msg_type = MSG_FILE_LAST_FRAGMENT
                        else:
                            msg_type = MSG_FILE_FRAGMENT

                        fragment_number = i + 1
                        if fragment_number > 65535:
                            print("Fragment number exceeds maximum value (65535). Skipping fragment.")
                            break

                        sequence_number = (message_id << 16) | fragment_number
                        message_packet = create_message(msg_type, sequence_number, fragment)

                        if simulate_fault and i == corrupt_fragment_index:
                            print(f"\nSimulating fault in file fragment {fragment_number} (Sequence number {sequence_number})")
                            message_packet = bytearray(message_packet)
                            data_start_index = 9
                            if len(message_packet) > data_start_index:
                                message_packet[data_start_index] ^= 0x01
                            else:
                                print("Cannot corrupt data: fragment packet too short")
                            message_packet = bytes(message_packet)

                        sent_fragments[sequence_number] = (msg_type, fragment)
                        max_retries = 5
                        retry_count = 0
                        while retry_count < max_retries:
                            sock.sendto(message_packet, addr)
                            print(f"\nSent fragment {fragment_number} (Sequence number {sequence_number})")
                            with ack_condition:
                                ack_received = ack_condition.wait_for(
                                    lambda: sequence_number in acknowledged_sequences or sequence_number in nacknowledged_sequences,
                                    timeout=5
                                )
                                if ack_received:
                                    if sequence_number in acknowledged_sequences:
                                        print(f"ACK received for fragment {fragment_number} (Sequence number {sequence_number})")
                                        acknowledged_sequences.remove(sequence_number)
                                        break
                                    elif sequence_number in nacknowledged_sequences:
                                        print(f"NAK received for fragment {fragment_number} (Sequence number {sequence_number}), retransmitting")
                                        nacknowledged_sequences.remove(sequence_number)
                                        retry_count += 1
                                        msg_type, fragment = sent_fragments[sequence_number]
                                        message_packet = create_message(msg_type, sequence_number, fragment)
                                else:
                                    retry_count += 1
                                    print(f"Timeout waiting for ACK/NAK for fragment {fragment_number}, retransmitting (Attempt {retry_count}/5)")

                    print(f"\n{'-' * 50}")
                    print(f"Sent file:")
                    print(f"Name: {file_name}")
                    print(f"Size: {total_size} bytes")
                    print(f"Fragments: {num_fragments}")
                    print(f"{'-' * 50}\n")
                except FileNotFoundError:
                    print("\nFile not found. Please check the file path and try again.")
                except Exception as e:
                    print(f"\nFailed to send file: {e}")
            else:
                message_bytes = message.encode()
                total_size = len(message_bytes)
                if total_size <= MAX_DATA_SIZE:
                    sequence_number = 0
                    sent_fragments[sequence_number] = (MSG_DEFAULT, message_bytes)
                    message_packet = create_message(MSG_DEFAULT, sequence_number, message_bytes)

                    if simulate_fault:
                        print("\nSimulating fault in message")
                        message_packet = bytearray(message_packet)
                        data_start_index = 9
                        if len(message_packet) > data_start_index:
                            message_packet[data_start_index] ^= 0x01
                        else:
                            print("Cannot corrupt data: message packet too short")
                        message_packet = bytes(message_packet)

                    max_retries = 5
                    retry_count = 0
                    while retry_count < max_retries:
                        sock.sendto(message_packet, addr)
                        print(f"\nSent message (Sequence number {sequence_number})")
                        with ack_condition:
                            ack_received = ack_condition.wait_for(
                                lambda: sequence_number in acknowledged_sequences or sequence_number in nacknowledged_sequences,
                                timeout=5
                            )
                            if ack_received:
                                if sequence_number in acknowledged_sequences:
                                    print(f"ACK received for message (Sequence number {sequence_number})")
                                    acknowledged_sequences.remove(sequence_number)
                                    break
                                elif sequence_number in nacknowledged_sequences:
                                    print(f"NAK received for message (Sequence number {sequence_number}), retransmitting")
                                    nacknowledged_sequences.remove(sequence_number)
                                    retry_count += 1
                                    msg_type, message_bytes = sent_fragments[sequence_number]
                                    message_packet = create_message(msg_type, sequence_number, message_bytes)
                            else:
                                retry_count += 1
                                print(f"Timeout waiting for ACK/NAK for message, retransmitting (Attempt {retry_count}/5)")
                    else:
                        print(f"\nFailed to receive ACK/NAK for message after {max_retries} attempts")
                        stop_event.set()
                        break
                else:
                    fragments = [message_bytes[i:i+MAX_DATA_SIZE] for i in range(0, total_size, MAX_DATA_SIZE)]
                    num_fragments = len(fragments)
                    corrupt_fragment_index = num_fragments - 1 if simulate_fault else -1
                    message_id = message_id_counter
                    message_id_counter = (message_id_counter + 1) % 65536

                    for i, fragment in enumerate(fragments):
                        if i == num_fragments - 1:
                            msg_type = MSG_LAST_FRAGMENT
                        else:
                            msg_type = MSG_FRAGMENT

                        fragment_number = i
                        if fragment_number > 65535:
                            print("Fragment number exceeds maximum value (65535). Skipping fragment.")
                            break

                        sequence_number = (message_id << 16) | fragment_number
                        message_packet = create_message(msg_type, sequence_number, fragment)

                        if simulate_fault and i == corrupt_fragment_index:
                            print(f"\nSimulating fault in fragment {fragment_number} (Sequence number {sequence_number})")
                            message_packet = bytearray(message_packet)
                            data_start_index = 9
                            if len(message_packet) > data_start_index:
                                message_packet[data_start_index] ^= 0x01
                            else:
                                print("Cannot corrupt data: fragment packet too short")
                            message_packet = bytes(message_packet)

                        sent_fragments[sequence_number] = (msg_type, fragment)
                        max_retries = 5
                        retry_count = 0
                        while retry_count < max_retries:
                            sock.sendto(message_packet, addr)
                            print(f"\nSent fragment {fragment_number} (Sequence number {sequence_number})")
                            with ack_condition:
                                ack_received = ack_condition.wait_for(
                                    lambda: sequence_number in acknowledged_sequences or sequence_number in nacknowledged_sequences,
                                    timeout=5
                                )
                                if ack_received:
                                    if sequence_number in acknowledged_sequences:
                                        print(f"ACK received for fragment {fragment_number} (Sequence number {sequence_number})")
                                        acknowledged_sequences.remove(sequence_number)
                                        break
                                    elif sequence_number in nacknowledged_sequences:
                                        print(f"NAK received for fragment {fragment_number} (Sequence number {sequence_number}), retransmitting")
                                        nacknowledged_sequences.remove(sequence_number)
                                        retry_count += 1
                                        msg_type, fragment = sent_fragments[sequence_number]
                                        message_packet = create_message(msg_type, sequence_number, fragment)
                                else:
                                    retry_count += 1
                                    print(f"Timeout waiting for ACK/NAK for fragment {fragment_number}, retransmitting (Attempt {retry_count}/5)")
                    print(f"\n{'-' * 50}")
                    print(f"Sent message:")
                    print(f"Size: {total_size} bytes")
                    print(f"Fragments: {num_fragments}")
                    print(f"{'-' * 50}\n")
        except Exception as e:
            print(f"\nSending error: {e}")
            stop_event.set()
            break

def main():
    while True:
        mode = input("\nSelect mode (server/client/exit): ")
        if mode == 'server':
            local_host = input("Enter host to bind (default 'localhost'): ") or 'localhost'
            port_input = input("Enter port to bind (default 65432): ") or '65432'
            try:
                local_port = int(port_input)
                start_server(local_host, local_port)
            except ValueError:
                print("\nInvalid port number.")
        elif mode == 'client':
            local_host = input("Enter your local host to bind (default 'localhost'): ") or 'localhost'
            local_port_input = input("Enter your local port to bind (default 65433): ") or '65433'
            server_host = input("Enter server host to connect (default 'localhost'): ") or 'localhost'
            server_port_input = input("Enter server port to connect (default 65432): ") or '65432'
            try:
                local_port = int(local_port_input)
                server_port = int(server_port_input)
                start_client(local_host, local_port, server_host, server_port)
            except ValueError:
                print("\nInvalid port number.")
        elif mode == 'exit':
            print("\nExiting program.")
            break
        else:
            print("\nInvalid mode selected.")

if __name__ == "__main__":
    main()