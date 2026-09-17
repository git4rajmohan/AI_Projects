import pytest
from ragas import SingleTurnSample
from ragas.metrics import RubricsScore


@pytest.mark.asyncio
async def test_rubric_score(llm_wrapper, getData):
    rubrics = {
        "score1_description": "The response is incorrect, irrelevant, or does not align with the ground truth.",
        "score2_description": "The response partially matches the ground truth but includes significant errors, omissions, or irrelevant information.",
        "score3_description": "The response generally aligns with the ground truth but may lack detail, clarity, or have minor inaccuracies.",
        "score4_description": "The response is mostly accurate and aligns well with the ground truth, with only minor issues or missing details.",
        "score5_description": "The response is fully accurate, aligns completely with the ground truth, and is clear and detailed.",
    }

    rubrics_score = RubricsScore(rubrics=rubrics, llm=llm_wrapper)
    score = await rubrics_score.single_turn_ascore(getData)
    print(f"the score is {score}")
    assert score > 4


@pytest.fixture
def getData():
    sample = SingleTurnSample(
        user_input="Where is the Eiffel Tower located?",
        response="The Eiffel Tower is located in london.",
        reference="The Eiffel Tower is located in Paris.",

    )
    return sample
