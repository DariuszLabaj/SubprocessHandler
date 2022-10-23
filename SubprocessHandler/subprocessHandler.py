from subprocess import Popen, PIPE  # nosec
import time
from threading import Thread
import sys
from abc import ABC
from typing import IO, List
from queue import Queue, Empty

ON_POSIX = "posix" in sys.builtin_module_names


class SubprocessHandlerException(Exception):
    ...


class TimeoutException(SubprocessHandlerException):
    ...


def _enqueue_output(out: IO[str], queue: Queue):
    for line in iter(out.readline, b""):
        queue.put(line)
    out.close()


_stdoutQueue = Queue()


class SubprocessHandler(ABC):
    @property
    def ReceiveBuffer(self) -> List[str]:
        return self.__receiveBuffer

    @property
    def TerminationData(self) -> None | int:
        return self.__terminationData

    @property
    def isAllive(self) -> bool:
        if self.__subprocess is None:
            self.__terminationData = None
            return False
        self.__terminationData = self.__subprocess.poll()
        return self.__terminationData is None

    def __init__(
        self,
        path: str,
        arguments: list[str],
        eot: str | None = None,
    ):
        self.__path = path
        self.__arguments = arguments
        self.__eot = eot
        self.__subprocess: Popen | None = None
        self.__terminationData: int | None = None
        self.__receiveBuffer: List[str] = []

    def __appendReceiveBuffer(self, data: str) -> None:
        self.__receiveBuffer.append(data)

    def __clearReceiveBuffer(self) -> None:
        self.__receiveBuffer: List[str] = []

    def run(self) -> None:
        self.__subprocess = Popen(
            [self.__path] + self.__arguments,
            stdin=PIPE,
            stdout=PIPE,
            universal_newlines=True,
        )
        thread = Thread(
            target=_enqueue_output, args=(self.__subprocess.stdout, _stdoutQueue)
        )
        thread.daemon = True
        thread.start()

    def send(self, data: str):
        if self.__subprocess is None:
            return
        datToSend = data + self.__eot if self.__eot is not None else data
        dataSent = False
        if self.__subprocess.stdin is None:
            return
        self.__subprocess.stdin.write(datToSend)
        self.__subprocess.stdin.flush()
        dataSent = True
        if dataSent:
            self.__clearReceiveBuffer()
        return

    def receive(self) -> bool:
        if self.__subprocess is None:
            return
        try:
            line: str = _stdoutQueue.get()
        except Empty:
            return
        if line != "":
            self.__appendReceiveBuffer(line.replace("\n", ""))
            return
        return

    def terminate(self):
        if self.__subprocess is not None:
            self.__subprocess.terminate()

    def awaitReceive(self, timeout: float):
        def awaitForDataStart():
            timeout_time = time.time() + timeout
            while _stdoutQueue.empty() and timeout_time > time.time():
                time.sleep(0.1)
            return _stdoutQueue.empty()

        def getTheData():
            while not _stdoutQueue.empty():
                self.receive()

        noData = awaitForDataStart()
        if noData:
            raise TimeoutException("Timed out, data not present")
        getTheData()
