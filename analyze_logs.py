import sqlite3


def analyze():
    conn = sqlite3.connect("data/jarvis.db")
    cursor = conn.cursor()

    print("\n=== USO APP ===")
    cursor.execute("SELECT app_name, SUM(duration) FROM activity_log GROUP BY app_name")

    for app, duration in cursor.fetchall():
        print(app, round(duration / 3600, 2), "h")

    cursor.execute("SELECT COUNT(*) FROM activity_log")
    print("\nRows:", cursor.fetchone()[0])


if __name__ == "__main__":
    analyze()