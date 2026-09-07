from app import create_app

app = create_app()

if __name__ == "__main__":
    # Local dev only. Render will run this via gunicorn instead
    # (see render.yaml / start command), never this __main__ block.
    app.run(debug=True)
