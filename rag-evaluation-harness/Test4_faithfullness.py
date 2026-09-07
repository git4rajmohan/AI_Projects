import pytest
from ragas import SingleTurnSample
from ragas.metrics.collections import Faithfulness

from utils import load_test_data, get_llm_response


@pytest.mark.parametrize("getData", load_test_data("Test4.json"), indirect=True)
@pytest.mark.asyncio
async def test_faithfulness(llm_wrapper, getData):
    faithful = Faithfulness(llm=llm_wrapper)
    score = await faithful.ascore(
        user_input=getData.user_input,
        response=getData.response,
        retrieved_contexts=getData.retrieved_contexts,
    )
    print(f"Faithfulness score: {score.value}")
    assert score.value > 0.8


@pytest.fixture
def getData(request):
    test_data = request.param
    responseDict = get_llm_response(test_data)

    sample = SingleTurnSample(
        user_input=test_data["question"],
        response=responseDict["answer"],
        retrieved_contexts=[doc["page_content"] for doc in responseDict.get("retrieved_docs")]

    )
    return sample
