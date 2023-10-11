from __future__ import annotations

from typing import TYPE_CHECKING

from sec_parser.processing_steps.abstract_elementwise_processing_step import (
    AbstractElementwiseProcessStep,
    ElementwiseProcessingContext,
)
from sec_parser.semantic_elements.highlighted_text_element import (
    HighlightedTextElement,
    TextStyle,
)

if TYPE_CHECKING:
    from sec_parser.semantic_elements.abstract_semantic_element import (
        AbstractSemanticElement,
    )


class HighlightedTextParsingStep(AbstractElementwiseProcessStep):
    """
    HighlightedText class for transforming elements into HighlightedText instances.

    This step scans through a list of semantic elements and changes it,
    primarily by replacing suitable candidates with HighlightedText instances.
    """

    def __init__(
        self,
        types_to_process: set[type[AbstractSemanticElement]] | None = None,
        types_to_exclude: set[type[AbstractSemanticElement]] | None = None,
    ) -> None:
        super().__init__(
            types_to_process=types_to_process,
            types_to_exclude=types_to_exclude,
        )

    def _process_element(
        self,
        element: AbstractSemanticElement,
        _: ElementwiseProcessingContext,
    ) -> AbstractSemanticElement:
        styles_metrics = element.html_tag.get_text_styles_metrics()
        style: TextStyle = TextStyle.from_style_string(styles_metrics)
        if not style:
            return element
        return HighlightedTextElement.convert_from(element, style=style)
