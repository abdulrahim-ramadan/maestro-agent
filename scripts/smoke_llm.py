from maestro.config import Settings
from maestro.llm.client import LLMClient


def main() -> None:
    client = LLMClient(Settings.from_env())
    messages = [{"role": "user", "content": "Say hello in German in one sentence"}]
    client.stream(messages, on_token=lambda token: print(token, end="", flush=True))
    print()


if __name__ == "__main__":
    main()
