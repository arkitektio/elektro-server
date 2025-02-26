from core.models import Image, Dataset
from django.contrib.auth import get_user_model


def test_create_model(db):
    # Create a new instance of MyModel
    user = get_user_model().objects.create_user(
        username="testuser", password="123456789"
    )

    dataset = Dataset.objects.create(
        name="Test Model", description="This is a test model",
        creator=user,
    )
    my_model = Image.objects.create(
        dataset=dataset,
        creator=user,
    )

    # Assert that the model was created successfully
    assert my_model.id == 1
