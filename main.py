import time

from core.observer import Observer
from data.database import init_db


def main():

    init_db()

    observer = Observer()

    print("Jarvis started...")

    while True:

        observer.observe()

        time.sleep(5)


if __name__ == "__main__":
    main()