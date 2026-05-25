from core.observer import Observer
from data.database import Database


def run():
    db = Database()
    observer = Observer(db)
    observer.observe()


if __name__ == "__main__":
    run()