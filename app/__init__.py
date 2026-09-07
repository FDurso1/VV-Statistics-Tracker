
from flask import Flask

def create_app():
    app = Flask(__name__)

    from app.routes import bp
    app.register_blueprint(bp)

    from app.formatting import username_from_url
    app.jinja_env.filters["username_from_url"] = username_from_url # type: ignore

    return app
