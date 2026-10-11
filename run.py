from app import create_app
from app.acquisition.scheduler import start_scheduler, stop_scheduler

app = create_app()

if __name__ == "__main__":
    start_scheduler()
    try:
        app.run(debug=True, use_reloader=False)
    finally:
        stop_scheduler()