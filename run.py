import os
import sys
from app import create_app
from app.utils.seed_data import seed_database

app = create_app(os.getenv('FLASK_ENV', 'development'))

@app.cli.command('seed-db')
def seed_db_command():
    """Seed the database with realistic demo data."""
    seed_database(verbose=True)

if __name__ == '__main__':
    if '--seed' in sys.argv:
        with app.app_context():
            print("[*] Running database seeding...")
            seed_database(verbose=True)
            print("[+] Seeding completed successfully.")
    else:
        print("=" * 65)
        print("  Advanced Attendance Management System - COP Project")
        print("  Status: Phase 9 Complete (Production & Academic Demo Ready)")
        print("  Running on: http://127.0.0.1:5000")
        print("  Health check: http://127.0.0.1:5000/health")
        print("=" * 65)
        app.run(host='127.0.0.1', port=5000, debug=True)
