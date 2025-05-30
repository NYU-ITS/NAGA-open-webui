from portkey_ai import createHeaders, PORTKEY_GATEWAY_URL
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
import yaml


def read_yaml_as_dict(file_path):
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

def get_llm(config_path="src/config.yaml", model_name="gpt-4o"):
    config = read_yaml_as_dict(config_path)
    portkey_headers = createHeaders(
        api_key=config["portkey"]["chat"]["api_key"],
        virtual_key=config["portkey"]["chat"]["openai_virtual_key"]
    )
    return ChatOpenAI(
        api_key="***",
        base_url=config["portkey"]["base_url"],
        default_headers=portkey_headers,
        model=model_name
    )


def get_embedding_model(config_path="src/config.yaml"):
    config = read_yaml_as_dict(config_path)
    portkey_headers = createHeaders(
        api_key=config["portkey"]["embeddings"]["api_key"],
        virtual_key=config["portkey"]["embeddings"]["virtual_key"]
    )
    return OpenAIEmbeddings(
        api_key="***",
        base_url=config["portkey"]["base_url"],
        default_headers=portkey_headers
    )