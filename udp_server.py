import socket
import sys
import time
import _thread
from timer import Timer
import packet

class UDPServer:
    SW = 0
    GBN = 1
    SR = 2
    SLEEP_INTERVAL = 0.00001
    def __init__(self, file_name, packet_size, window_size, RTO, port=5000):
        self.port = port
        self.file = open(file_name, "rb")
        if self.file is None:
            print("File not found")
            del self
            return
        self.packet_size = packet_size
        self.window_size = window_size
        self.RTO = RTO
        self.timer = Timer(RTO)
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.mutex = _thread.allocate_lock()
        self.base = 0
    
    def run(self, tcp_algorithm):
        self.__sock.bind(('localhost', self.port))
        packets = []
        seq_num = 0
        while True:
            data = self.file.read(self.packet_size)
            if not data:
                break
            packets.append(packet.make(seq_num, data))
            seq_num += 1
        print("File read")
        print("Server listening on port", self.port, "...")
        while True:
            message, address = self.__sock.recvfrom(1024)
            if message != b"SYN":
                continue
            print("Connection request from", address)

            if tcp_algorithm == UDPServer.SW:
                self.__stop_and_wait(address, packets)
            elif tcp_algorithm == UDPServer.GBN:
                self.__go_back_n(address, packets)
            elif tcp_algorithm == UDPServer.SR:
                self.__selective_repeat(address, packets)
            else:
                print("Invalid TCP algorithm")
            print("Connection closed")

    def __stop_and_wait(self, client_address, packets):
        num_packets = len(packets)
        self.base = 0

        _thread.start_new_thread(self.__SW_receive, (client_address, num_packets,))

        while self.base < num_packets:
            self.mutex.acquire()
            self.__sock.sendto(packets[self.base], client_address)
            print("Sent packet", self.base)
            
            if not self.timer.running():
                self.timer.start()
            self.mutex.release()

            while self.timer.running() and not self.timer.timeout():
                self.mutex.acquire()
                time.sleep(UDPServer.SLEEP_INTERVAL)
                self.mutex.release()
        self.__sock.sendto(packet.make_empty(), client_address)
        print("File sent")
        return
    
    def __SW_receive(self, client_address, num_packets):
        while True:
            if self.base >= num_packets:
                self.timer.stop()
                return
            pkt, address = self.__sock.recvfrom(1024)
            ack, _ = packet.extract(pkt)
            if address != client_address:
                continue
            if ack == self.base:
                self.mutex.acquire()
                print("Received ACK", ack)
                self.base += 1
                self.timer.stop()
                self.mutex.release()  
        return


    def __go_back_n(self, client_address, packets):
        num_packets = len(packets)
        next_to_send = 0
        self.base = 0

        _thread.start_new_thread(self.__GBN_receive, (client_address, num_packets, ))

        while self.base < num_packets:
            self.mutex.acquire()
            while next_to_send < self.base + self.window_size:
                if next_to_send >= num_packets:
                    break
                self.__sock.sendto(packets[next_to_send], client_address)
                print("Sent packet", next_to_send)
                next_to_send += 1
            
            if not self.timer.running():
                self.timer.start()

            while self.timer.running() and not self.timer.timeout():
                self.mutex.release()
                time.sleep(UDPServer.SLEEP_INTERVAL)
                self.mutex.acquire()

            if self.timer.timeout():
                print("Timeout, sequence number = ", self.base)
                self.timer.stop()
                next_to_send = self.base
            self.mutex.release()
        self.__sock.sendto(packet.make_empty(), client_address)
        print("File sent")
        return

    def __GBN_receive(self, client_address, num_packets):
        while True:
            if self.base >= num_packets:
                self.timer.stop()
                return
            pkt, address = self.__sock.recvfrom(1024)
            ack, _ = packet.extract(pkt)
            if address != client_address:
                continue
            if ack >= self.base:
                self.mutex.acquire()
                print("Received ACK", ack)
                self.base = ack + 1
                self.timer.stop()
                self.mutex.release()
        return


    def __selective_repeat(self, client_address, packets):
        num_packets = len(packets)
        self.base = 0
        next_to_send = 0
        self.acked_packets = [False] * (num_packets + 1)

        _thread.start_new_thread(self.__SR_receive, (client_address, packets))

        while self.base < num_packets:
            self.mutex.acquire()
            while next_to_send < self.base + self.window_size:
                if next_to_send >= num_packets:
                    break
                self.__sock.sendto(packets[next_to_send], client_address)
                print("Sent packet ", next_to_send)
                next_to_send += 1

            if not self.timer.running():
                self.timer.start()
            self.mutex.release()

            while self.timer.running() and not self.timer.timeout():
                self.mutex.acquire()
                time.sleep(UDPServer.SLEEP_INTERVAL)
                self.mutex.release()

            if self.timer.timeout():
                print("Timeout, sequence number = ", self.base)
                self.timer.stop()
                next_to_send = self.base
        self.__sock.sendto(packet.make_empty(), client_address)
        print("File sent")
        return

    def __SR_receive(self, client_address, packets):
        while True:
            if self.base >= len(packets):
                self.timer.stop()
                return
            pkt, address = self.__sock.recvfrom(1024)
            ack, _ = packet.extract(pkt)
            if ack >= len(packets):
                self.timer.stop()
                return
            ack += 1
            if address != client_address:
                continue
            if ack > self.base:
                self.mutex.acquire()
                print("Received ACK", ack)
                self.base = ack
                if self.acked_packets[ack] == True:
                    self.__sock.sendto(packets[ack], client_address)
                    print("Sent packet", ack)
                    self.timer.stop()
                    self.timer.start()
                else:
                    self.acked_packets[ack] = True
                    self.timer.stop()
                self.mutex.release()

    def __del__(self):
        if self.__sock is not None:
          self.__sock.close()
        if self.file is not None:
          self.file.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Expected tcp algorithm as command line argument')
        print('tcp algorithm numbers:\n 0: stop and wait,\n 1: go back n,\n 2: selective repeat')
        exit()
    file_name = "./loco.jpg"
    packet_size = 25 * 1024 # 25 KB
    window_size = 7  # 7 packets (betwenn 5 and 10)
    RTO = 0.2 # 200 ms
    tcp_algorithm = int(sys.argv[1])
    server = UDPServer(file_name, packet_size, window_size, RTO)
    server.run(tcp_algorithm)
    
