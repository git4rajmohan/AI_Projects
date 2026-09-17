import pytest
from ragas import SingleTurnSample
from ragas.metrics.collections import (
    ContextPrecisionWithReference,
    ContextRecall,
    ContextRelevance,
    Faithfulness,
    FactualCorrectness,
    ResponseGroundedness,
)

from utils import load_test_data, get_llm_response


@pytest.mark.parametrize("getData",
                         load_test_data("Test5.json"), indirect=True)
@pytest.mark.asyncio
async def test_all_non_embedding_metrics(llm_wrapper, getData):
    metrics = [
        (
            "Faithfulness",
            Faithfulness(llm=llm_wrapper),
            {
                "user_input": getData.user_input,
                "response": getData.response,
                "retrieved_contexts": getData.retrieved_contexts,
            },
        ),
        (
            "Factual correctness",
            FactualCorrectness(llm=llm_wrapper),
            {
                "response": getData.response,
                "reference": getData.reference,
            },
        ),
        (
            "Context recall",
            ContextRecall(llm=llm_wrapper),
            {
                "user_input": getData.user_input,
                "retrieved_contexts": getData.retrieved_contexts,
                "reference": getData.reference,
            },
        ),
        (
            "Context precision with reference",
            ContextPrecisionWithReference(llm=llm_wrapper),
            {
                "user_input": getData.user_input,
                "reference": getData.reference,
                "retrieved_contexts": getData.retrieved_contexts,
            },
        ),
        (
            "Response groundedness",
            ResponseGroundedness(llm=llm_wrapper),
            {
                "response": getData.response,
                "retrieved_contexts": getData.retrieved_contexts,
            },
        ),
        (
            "Context relevance",
            ContextRelevance(llm=llm_wrapper),
            {
                "user_input": getData.user_input,
                "retrieved_contexts": getData.retrieved_contexts,
            },
        ),
    ]

    for metric_name, metric, metric_inputs in metrics:
        score = await metric.ascore(**metric_inputs)
        print(f"{metric_name} score is: {score.value}")


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
