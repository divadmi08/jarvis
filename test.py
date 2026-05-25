import sqlite3

DB_PATH = "data/jarvis.db"  # cambia se il tuo path è diverso

def test_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("\n🧪 === TEST DATABASE JARVIS ===\n")

    # 1. Conta righe totali
    cursor.execute("SELECT COUNT(*) FROM activity_log")
    total = cursor.fetchone()[0]
    print(f"📊 Totale righe activity_log: {total}")

    # 2. Conta duplicati esatti (start + end)
    cursor.execute("""
        SELECT start_time, end_time, COUNT(*)
        FROM activity_log
        GROUP BY start_time, end_time
        HAVING COUNT(*) > 1
    """)
    duplicates = cursor.fetchall()

    print(f"\n🔁 Coppie duplicate (start/end): {len(duplicates)}")

    for d in duplicates[:10]:
        print("   -", d)

    # 3. Mostra ultimi log
    cursor.execute("""
        SELECT app_name, start_time, end_time, duration
        FROM activity_log
        ORDER BY id DESC
        LIMIT 10
    """)
    last_logs = cursor.fetchall()

    print("\n🧾 Ultimi 10 log:")
    for log in last_logs:
        print("   ", log)

    print("\n✅ TEST COMPLETATO\n")

if __name__ == "__main__":
    test_db()