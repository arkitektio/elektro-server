from datalayer import base_models
from strawberry.experimental import pydantic


@pydantic.input(model=base_models.RequestMediaUploadInput, all_fields=True)
class RequestMediaUploadInput:
    """
    Docstring for RequestMediaUploadInput
    """

    pass


@pydantic.input(model=base_models.FinishMediaUploadInput, all_fields=True)
class FinishMediaUploadInput:
    """
    Docstring for FinishMediaUploadInput
    """

    pass


@pydantic.input(model=base_models.RequestMediaAccessInput, all_fields=True)
class RequestMediaAccessInput:
    """
    Docstring for RequestMediaAccessInput
    """

    pass


@pydantic.input(model=base_models.RequestGeneralMediaAccessInput, all_fields=True)
class RequestGeneralMediaAccessInput:
    """
    Docstring for RequestGeneralMediaAccessInput
    """

    pass


@pydantic.input(model=base_models.RequestBigFileUploadInput, all_fields=True)
class RequestBigFileUploadInput:
    """
    Docstring for RequestMediaUploadInput
    """

    pass


@pydantic.input(model=base_models.FinishBigFileUploadInput, all_fields=True)
class FinishBigFileUploadInput:
    """
    Docstring for FinishMediaUploadInput
    """

    pass


@pydantic.input(model=base_models.RequestBigFileAccessInput, all_fields=True)
class RequestBigFileAccessInput:
    """
    Docstring for RequestBigFileAccessInput
    """

    pass


@pydantic.input(model=base_models.RequestZarrUploadInput, all_fields=True)
class RequestZarrUploadInput:
    """
    Docstring for RequestZarrUploadInput
    """

    pass


@pydantic.input(model=base_models.FinishZarrUploadInput, all_fields=True)
class FinishZarrUploadInput:
    """
    Docstring for FinishZarrUploadInput
    """

    pass


@pydantic.input(model=base_models.RequestZarrAccessInput, all_fields=True)
class RequestZarrAccessInput:
    """
    Docstring for RequestZarrAccessInput
    """

    pass


@pydantic.input(model=base_models.RequestParquetUploadInput, all_fields=True)
class RequestParquetUploadInput:
    """
    Docstring for RequestParquetUploadInput
    """

    pass


@pydantic.input(model=base_models.FinishParquetUploadInput, all_fields=True)
class FinishParquetUploadInput:
    """
    Docstring for FinishParquetUploadInput
    """

    pass


@pydantic.input(model=base_models.RequestParquetAccessInput, all_fields=True)
class RequestParquetAccessInput:
    """
    Docstring for RequestParquetAccessInput
    """

    pass
