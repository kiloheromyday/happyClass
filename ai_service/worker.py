"""Run with python -m ai_service.worker. SIGTERM leaves unacked work recoverable."""
import logging
import signal
import socket
import time
from uuid import uuid4

from ai_service.result_queue import get_queue
from backend.app.repositories.database import initialize_database


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    initialize_database()
    queue = get_queue()
    consumer = socket.gethostname() + '-' + uuid4().hex[:8]
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        try:
            count = queue.run_once(consumer)
            if count:
                logging.info('Processed %d queue deliveries', count)
        except Exception as error:
            logging.warning('Queue temporarily unavailable: %s', type(error).__name__)
            time.sleep(2)


if __name__ == '__main__':
    main()
