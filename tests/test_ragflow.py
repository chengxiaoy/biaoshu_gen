import json

import pytest
from openai import OpenAI

pytestmark = pytest.mark.e2e   # 默认排除（server 路由异常时 openai 客户端会挂很久）

model = "58d65008a5e911f197ea4b98b962e197"
client = OpenAI(api_key="ragflow-vo7__QJboi6KJrq5CZTyuS1Co_tx5-c0vcS96agGyyo", base_url="http://localhost:9380/api/v1/openai/cd276f7aa6a011f1a21e854a733b718a")


def test_ragflow():
    stream = False
    reference = True
    question = "给我BLIP的架构图"
    request_kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": """
You are an intelligent assistant. Your primary function is to answer questions based strictly on the provided knowledge base.
**Essential Rules:**
    - Your answer must be derived **solely** from this dataset: `{knowledge}`.
    - **When information is available**: Summarize the content to give a detailed answer.
    - **When information is unavailable**: Your response must contain this exact sentence: "The answer you are looking for is not found in the dataset!"
    - **Always consider** the entire conversation history."""},
            {"role": "user", "content": f"{question}"}
        ],
    extra_body={
        "reasoning":0,
        "reference": reference,
        "reference_metadata": {
            "include": True,
            "fields": ["author", "year", "source"],
        },
    },
    )

    if stream:
        completion = client.chat.completions.create(stream=True, **request_kwargs)
        for chunk in completion:
            print(chunk)
    else:
        resp = client.chat.completions.with_raw_response.create(
            stream=False, **request_kwargs
        )
        print("status:", resp.http_response.status_code)
        raw_text = resp.http_response.text
        print("raw:", raw_text)

        data = json.loads(raw_text)
        print("assistant:", data["choices"][0]["message"].get("content"))
        print("reference:", data["choices"][0]["message"].get("reference"))


if __name__ == "__main__":
  test_ragflow()