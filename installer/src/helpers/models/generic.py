from typing import Annotated

from pydantic import StringConstraints


EmptyString = Annotated[str, StringConstraints(max_length=0)]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
