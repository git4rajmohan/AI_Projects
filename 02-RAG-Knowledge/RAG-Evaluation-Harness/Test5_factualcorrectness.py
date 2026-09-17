import pytest
from ragas import SingleTurnSample
from ragas.metrics.collections import FactualCorrectness

from utils import load_test_data, get_llm_response


@pytest.mark.parametrize("getData",
                         load_test_data("Test5.json"), indirect=True)
@pytest.mark.asyncio
async def test_factual_correctness(llm_wrapper, getData):
    factual_correctness = FactualCorrectness(llm=llm_wrapper)
    score = await factual_correctness.ascore(
        response=getData.response,
        reference=getData.reference,
    )
    print(f"Factual correctness score is: {score.value}")


@pytest.fixture
def getData(request):
    test_data = request.param
    responseDict = get_llm_response(test_data)
    sample = SingleTurnSample(
        user_input=test_data["question"],
        response=responseDict["answer"],
        retrieved_contexts=[doc["page_content"] for doc in responseDict.get("retrieved_docs")],
        reference=test_data["reference"]

    )
    return sample
