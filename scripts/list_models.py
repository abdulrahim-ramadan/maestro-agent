from openai import OpenAI

from maestro.config import Settings


def main() -> None:
    settings = Settings.from_env()
    client = OpenAI(api_key=settings.api_key, base_url=settings.base_url)
    for model_id in sorted(model.id for model in client.models.list()):
        print(model_id)


if __name__ == "__main__":
    main()
