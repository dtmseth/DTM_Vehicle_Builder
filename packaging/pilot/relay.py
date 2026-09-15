"""Local pilot TCP relay to one fixed service; never an HTTP CONNECT proxy.

Docker does not publish ports for an internal-only network. Only this stateless
relay joins the ingress network. Builder/LibreOffice retain no external route.
"""
import selectors
import socket
import socketserver
import threading


SLOTS = threading.BoundedSemaphore(32)


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        if not SLOTS.acquire(blocking=False):
            return
        try:
            self.request.settimeout(150)
            with socket.create_connection(("builder", 7665), timeout=5) as upstream:
                upstream.settimeout(150)
                with selectors.DefaultSelector() as selector:
                    selector.register(self.request, selectors.EVENT_READ, upstream)
                    selector.register(upstream, selectors.EVENT_READ, self.request)
                    while ready := selector.select(timeout=150):
                        for key, _ in ready:
                            data = key.fileobj.recv(65536)
                            if not data:
                                return
                            key.data.sendall(data)
        except OSError:
            pass
        finally:
            SLOTS.release()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", 7665), Relay) as server:
        server.serve_forever()
