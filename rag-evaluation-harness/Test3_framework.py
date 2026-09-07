import pytest
from ragas import SingleTurnSample
from ragas.metrics.collections import ContextRecall

from utils import get_llm_response, load_test_data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "getData",
    load_test_data("Test3_framework.json"),
    indirect=True
)
async def test_context_recall(llm_wrapper, getData):
    context_recall = ContextRecall(llm=llm_wrapper)
    score = await context_recall.ascore(
        user_input=getData.user_input,
        retrieved_contexts=getData.retrieved_contexts,
        reference=getData.reference,
    )
    print(score.value)
    assert score.value > 0.7








@pytest.fixture
def getData(request):
    test_data = request.param
    responseDict = get_llm_response(test_data)

    sample = SingleTurnSample(
        user_input=test_data["question"],
        retrieved_contexts=[
            document["page_content"] for document in responseDict["retrieved_docs"]
        ],
        reference=test_data["reference"]
    )
    return sample
