import os
from collections import Counter
from dataclasses import dataclass
from itertools import zip_longest
from _utils.misc import interleave_lists
from _utils.misc import normalize_company_name
from debug_tools.parser_output_visualizer._utils.misc import clean_user_input
from streamlit_extras.add_vertical_space import add_vertical_space

import sec_parser as sp
import streamlit as st
import streamlit_antd_components as sac
from _sec_parser import (
    download_html,
    get_metadata,
    get_semantic_elements,
    get_semantic_tree,
)
from _utils.misc import (
    PassthroughContext,
    get_pretty_class_name,
    remove_ix_tags,
    remove_duplicates_retain_order,
)
from _utils.streamlit_ import (
    st_expander_allow_nested,
    st_hide_streamlit_element,
    st_multiselect_allow_long_titles,
    st_radio,
)
from dateutil.parser import parse
from dateutil.tz import tzutc
from dotenv import load_dotenv
from sec_parser.data_sources.secapio_data_retriever import (
    SecapioApiKeyInvalidError,
    SecapioApiKeyNotSetError,
    SecapioDataRetriever,
)
from sec_parser.semantic_elements.semantic_elements import IrrelevantElement

load_dotenv()

USE_METADATA = True
DEFAULT_PAGE_SIZE = 50


def streamlit_app(
    *,
    run_page_config=True,
    extra_steps: list["ProcessStep"] | None = None,
) -> "StreamlitAppReturn":
    # Returned values
    html = None
    elements = None
    tree = None

    if run_page_config:
        st.set_page_config(
            page_icon="🏦",
            page_title="SEC Parser Output Visualizer",
            initial_sidebar_state="expanded",
            layout="wide",
        )
    st_expander_allow_nested()
    st_hide_streamlit_element("class", "stDeployButton")
    st_multiselect_allow_long_titles()

    HIDE_UI_ELEMENTS = False
    # Default values to avoid errors when HIDE_UI_ELEMENTS is True
    input_urls = []
    sections = ["part1item2"]
    htmls = []
    metadatas = []
    htmls_urls = []
    elements_lists = []
    trees = []
    tickers = ["AAPL", "GOOG"]
    left, right = st.columns(2)
    sidebar_left, sidebar_right = st.columns(2)
    element_column_count = 2
    do_expand_all = False
    do_element_render_html = True
    selected_step = 2
    do_interleave = False

    secapio_api_key_name = SecapioDataRetriever.API_KEY_ENV_VAR_NAME
    secapio_api_key = os.environ.get(secapio_api_key_name, "")
    secapio_api_key = st.session_state.get(secapio_api_key_name, "")
    if secapio_api_key_name not in os.environ:
        with st.sidebar.expander("API Key", expanded=not bool(secapio_api_key)):
            st.write(
                "The API key is required for parsing files that haven't been pre-downloaded."
                "You can obtain a free one from [sec-api.io](https://sec-api.io)."
            )
            secapio_api_key = st.text_input(
                type="password",
                label="Enter your API key:",
                value=secapio_api_key,
            )
            with st.expander("Why do I need an API key?"):
                st.write(
                    "We're currently using *sec-api.io* to handle the removal of the"
                    "title 10-Q page and to download 10-Q Section HTML files. In the"
                    "future, we aim to download these HTML files directly from the"
                    "SEC EDGAR. For now, you can get a free API key from"
                    "[sec-api.io](https://sec-api.io) and input it below."
                )
            st.session_state[secapio_api_key_name] = secapio_api_key
            msg = (
                "**Note:** Key will be deleted upon page refresh. We suggest"
                f"setting the `{secapio_api_key_name}` environment variable, possibly"
                "by creating an `.env` file at the root of the project. This method"
                "allows you to utilize the API key without the need for manual"
                "entry each time."
            )
            st.info(msg)

    if not HIDE_UI_ELEMENTS:
        tickers = []
        with st.sidebar:
            st.write("# Choose Reports")
            with PassthroughContext():  # replace with st.expander("") if needed
                FIND_BY_TICKER = "Ticker symbols"
                ENTER_URL_DIRECTLY = "URLs"
                data_source_option = sac.segmented(
                    items=[
                        sac.SegmentedItem(label=FIND_BY_TICKER),
                        sac.SegmentedItem(label=ENTER_URL_DIRECTLY),
                    ],
                    size="xs",
                    grow=True,
                )
                selected_ticker = data_source_option == FIND_BY_TICKER
                selected_url = data_source_option == ENTER_URL_DIRECTLY
                if selected_ticker:
                    CHOOSE_FROM_LIST = "Choose from list"
                    selected_ticker_selection_option = st.radio(
                        "Method to choose the ticker symbols",
                        [CHOOSE_FROM_LIST, "Enter manually"],
                        horizontal=True,
                        help="Select the method to choose the ticker symbols. The latest reports will be downloaded based on the tickers you choose.",
                    )
                    select_ticker = selected_ticker_selection_option == CHOOSE_FROM_LIST
                    if select_ticker:
                        tickers = st.multiselect(
                            label="Tickers:",
                            options=["AAPL", "GOOG"],
                            default=["AAPL", "GOOG"],
                        )
                    else:
                        tickers = clean_user_input(
                            st.text_input(
                                label="Tickers:",
                                value="AAPL,GOOG",
                                placeholder="AAPL",
                                help="Enter one or more ticker symbols, separated by commas.",
                            ),
                            split_char=",",
                        )
                    if not tickers:
                        st.info("Please select or enter at least one ticker.")
                        st.stop()
                if selected_url:
                    input_urls = clean_user_input(
                        st.text_area(
                            "Enter URLs (one per line)",
                            height=160,
                            placeholder="https://www.sec.gov/Archives/edgar/data/320193/000032019323000077/aapl-20230701.htm",
                            value="https://www.sec.gov/Archives/edgar/data/320193/000032019323000077/aapl-20230701.htm\nhttps://www.sec.gov/Archives/edgar/data/320193/000032019323000064/aapl-20230401.htm",
                        ),
                        split_lines=True,
                    )
                    if not input_urls:
                        st.info("Please enter at least one URL.")
                        st.stop()
                section_1_2, all_sections = st_radio(
                    "Select Report Sections",
                    ["Only MD&A", "All Report Sections"],
                    horizontal=True,
                    help="MD&A stands for Management Discussion and Analysis. It's a section of a company's annual report in which management discusses numerous aspects of the company, such as market dynamics, operating results, risk factors, and more.",
                )
                if section_1_2:
                    sections = ["part1item2"]
                elif all_sections:
                    sections = None

    try:
        assert tickers or input_urls
        for ticker in tickers:
            metadata = get_metadata(
                secapio_api_key, doc="10-Q", latest_from_ticker=ticker
            )
            metadatas.append(metadata)
            url = metadata["linkToFilingDetails"]
            html = download_html(
                secapio_api_key,
                doc="10-Q",
                url=url,
                sections=sections,
                ticker=ticker,
            )
            htmls_urls.append(url)
            htmls.append(html)
        for url in input_urls:
            html = download_html(
                secapio_api_key,
                doc="10-Q",
                url=url,
                sections=sections,
                ticker=None,
            )
            metadata = get_metadata(secapio_api_key, doc="10-Q", url=url)
            metadatas.append(metadata)
            htmls_urls.append(url)
            htmls.append(html)
    except SecapioApiKeyNotSetError:
        st.error("**Error**: API key not set. Please provide a valid API key.")
        st.stop()
    except SecapioApiKeyInvalidError:
        st.error("**Error**: Invalid API key. Please check your API key and try again.")
        st.stop()

    if not HIDE_UI_ELEMENTS:
        process_steps = [
            ProcessStep(
                title="Original",
                caption="From SEC EDGAR",
            ),
            ProcessStep(
                title="Parsed",
                caption="Semantic Elements",
            ),
            ProcessStep(
                title="Structured",
                caption="Semantic Tree",
            ),
            *(extra_steps or []),
        ]
        selected_step = 1 + sac.steps(
            [
                sac.StepsItem(
                    title=k.title,
                    description=k.caption,
                )
                for k in process_steps
            ],
            index=2,
            format_func=None,
            placement="horizontal",
            size="default",
            direction="horizontal",
            type="default",  # default, navigation
            dot=False,
            return_index=True,
        )

    for html in htmls:
        if selected_step >= 2:
            elements = get_semantic_elements(html)
            elements_lists.append(elements)

    if not HIDE_UI_ELEMENTS:
        do_expand_all = False
        do_interleave = False
        do_element_render_html = False
        element_column_count = 1 if len(htmls) != 2 else 2
        if selected_step >= 2 and selected_step <= 3:
            with st.sidebar:
                add_vertical_space(2)
                st.write("# View Options")
                with PassthroughContext():  # replace with st.expander("") if needed
                    counted_element_types = Counter(
                        element.get_direct_abstract_semantic_subclass()
                        for elements in elements_lists
                        for element in elements
                    )
                    format_cls = (
                        lambda cls: f'{counted_element_types[cls]}x {get_pretty_class_name(cls, base=True).replace("*","")}'
                    )
                    available_element_types = {
                        format_cls(cls): cls
                        for cls in sorted(
                            counted_element_types.keys(),
                            key=lambda x: counted_element_types[x],
                            reverse=True,
                        )
                    }
                    available_values = list(available_element_types.keys())
                    preselected_types = [
                        format_cls(cls)
                        for cls in available_element_types.values()
                        if cls != IrrelevantElement
                    ]
                    selected_types = st.multiselect(
                        "Filter Semantic Element types",
                        available_values,
                        preselected_types,
                        help=(
                            "**Semantic Elements** correspond to the semantic elements in SEC EDGAR documents."
                            " A semantic element refers to a meaningful unit within the document that serves a"
                            " specific purpose, such as a paragraph or a table. Unlike syntactic elements,"
                            " which structure the HTML, semantic elements carry vital information for"
                            " understanding the document's content."
                        ),
                    )
                    selected_types = [
                        available_element_types[k] for k in selected_types
                    ]

                    for elements in elements_lists:
                        elements[:] = [
                            e
                            for e in elements
                            if any(isinstance(e, t) for t in selected_types)
                        ]

                    left, right = st.columns(2)
                    with left:
                        RENDER_HTML = "Original"
                        selected_contents_option = st.selectbox(
                            label="Show Contents",
                            options=[RENDER_HTML, "HTML Code"],
                            index=0,
                        )
                        do_element_render_html = selected_contents_option == RENDER_HTML
                        if selected_step == 2:
                            do_expand_all = st.checkbox(
                                "Show Contents",
                                value=False,
                            )

                    with right:
                        if selected_step == 2:
                            element_column_count = st.number_input(
                                "Number of Columns",
                                min_value=1,
                                value=element_column_count,
                            )
                        if selected_step == 2 and len(htmls) >= 2:
                            do_interleave = st.checkbox(
                                "Interleave",
                                value=True,
                                help=(
                                    "When enabled, elements from multiple reports are displayed "
                                    "in an interleaved manner for easier comparison. The first "
                                    "element from the first report will be followed by the first "
                                    "element from the second report, and so on."
                                ),
                            )
                    sidebar_left, sidebar_right = st.columns(2)

    for elements in elements_lists:
        if selected_step >= 3:
            tree = get_semantic_tree(elements)
            trees.append(tree)

    if selected_step == 3:
        with right:
            expand_depth = st.number_input("Expand Depth", min_value=-1, value=0)

    def render_semantic_element(
        element: sp.AbstractSemanticElement,
        do_element_render_html: bool,
    ):
        if do_element_render_html:
            element_html = remove_ix_tags(str(element.html_tag._bs4))
            st.markdown(element_html, unsafe_allow_html=True)
        else:
            st.code(element.html_tag._bs4.prettify(), language="markup")

    if not USE_METADATA:
        metadatas = []
    if selected_step == 1 or selected_step == 3:
        for url, html, elements, tree, metadata in zip_longest(
            htmls_urls, htmls, elements_lists, trees, metadatas, fillvalue=None
        ):

            def get_label():
                company_name = normalize_company_name(metadata["companyName"])
                form_type = metadata["formType"]
                filed_at = (
                    parse(metadata["filedAt"]).astimezone(tzutc()).strftime("%b %d, %Y")
                )
                period_of_report = (
                    parse(metadata["periodOfReport"])
                    .astimezone(tzutc())
                    .strftime("%b %d, %Y")
                )
                return f"**{company_name}** | {form_type} filed on {filed_at} for the period ended {period_of_report}"

            with PassthroughContext() if len(htmls) == 1 else st.expander(
                get_label() if metadata else url.split("/")[-1],
                expanded=selected_step == 3 and expand_depth >= 0,
            ):
                if metadata:
                    url_buttons = [
                        dict(
                            label="sec.gov",
                            href=metadata["linkToHtml"],
                            icon="link",
                        ),
                        dict(
                            label="Full HTML",
                            href=metadata["linkToFilingDetails"],
                            icon="link",
                        ),
                    ]
                else:
                    url_buttons = [
                        dict(
                            label="sec.gov",
                            href=url,
                            icon="link",
                        ),
                    ]
                sac.buttons(
                    url_buttons,
                    label=None,
                    index=None,
                    format_func=None,
                    align="end",
                    position="top",
                    size="default",
                    direction="horizontal",
                    shape="default",
                    compact=True,
                    return_index=False,
                )

                def render_tree_node(tree_node: sp.TreeNode, _current_depth=0):
                    element = tree_node.semantic_element
                    expander_title = get_pretty_class_name(element.__class__, element)
                    with st.expander(
                        expander_title, expanded=expand_depth > _current_depth
                    ):
                        render_semantic_element(element, do_element_render_html)
                        for child in tree_node.children:
                            render_tree_node(child, _current_depth=_current_depth + 1)

                if selected_step == 1:
                    st.markdown(remove_ix_tags(html), unsafe_allow_html=True)
                    continue

                if selected_step == 3:
                    for root_node in tree.root_nodes:
                        render_tree_node(root_node)

    if selected_step == 2:
        titles_and_elements_per_report = []
        for elements, url, metadata in zip_longest(
            elements_lists, htmls_urls, metadatas, fillvalue=None
        ):
            element_source = ""
            if len(htmls_urls) > 1:
                if metadata:
                    company_name = normalize_company_name(metadata["companyName"])
                    if (
                        sum(
                            1
                            for m in metadatas
                            if normalize_company_name(m["companyName"]) == company_name
                        )
                        > 1
                    ):
                        period_of_report = (
                            parse(metadata["periodOfReport"])
                            .astimezone(tzutc())
                            .strftime("%Y-%m-%d")
                        )
                        element_source = f"*{company_name} {period_of_report}*"
                    else:
                        element_source = f"*{company_name}*"
                else:
                    element_source = url.split("/")[-1]
            titles_and_elements = []
            for element in elements:
                expander_title = get_pretty_class_name(
                    element.__class__, element, source=element_source
                )
                titles_and_elements.append((expander_title, element))
            titles_and_elements_per_report.append(titles_and_elements)

        if do_interleave:
            titles_and_elements = interleave_lists(titles_and_elements_per_report)
        else:
            titles_and_elements = [j for k in titles_and_elements_per_report for j in k]

        with sidebar_left:
            pagination_size = st.number_input(
                "Set Page Size",
                min_value=0,
                value=DEFAULT_PAGE_SIZE
                if len(titles_and_elements) > DEFAULT_PAGE_SIZE
                else 0,
                help=(
                    "Set the number of elements displayed per page. "
                    "Use this to manage the amount of information on the screen. "
                    "Set to 0 to disable pagination and show all elements at once."
                ),
            )
        if pagination_size:
            selected_page = sac.pagination(
                total=len(titles_and_elements),
                index=1,
                page_size=pagination_size,
                align="center",
                circle=False,
                disabled=False,
                jump=True,
                simple=False,
                show_total=True,
            )
            pagination_start_idx = (selected_page - 1) * pagination_size
            pagination_end_idx = selected_page * pagination_size
            titles_and_elements = titles_and_elements[
                pagination_start_idx:pagination_end_idx
            ]

        cols = st.columns(element_column_count)
        for i_col, col in enumerate(cols):
            for expander_title, element in titles_and_elements[
                i_col::element_column_count
            ]:
                with col:
                    with st.expander(expander_title, expanded=do_expand_all):
                        render_semantic_element(element, do_element_render_html)

    parsed_reports = []
    for url, html, elements, tree in zip(htmls_urls, htmls, elements_lists, trees):
        parsed_report = ParsedReport(
            url=url,
            html=html,
            elements=elements,
            tree=tree,
        )
        parsed_reports.append(parsed_report)
    return StreamlitAppReturn(
        parsed_reports=parsed_reports,
        selected_step=selected_step,
    )


@dataclass
class ParsedReport:
    url: str
    html: str
    elements: list[sp.AbstractSemanticElement]
    tree: sp.SemanticTree


@dataclass
class StreamlitAppReturn:
    parsed_reports: list[ParsedReport]
    selected_step: int


@dataclass
class ProcessStep:
    title: str
    caption: str


if __name__ == "__main__":
    streamlit_app()

    # ai_step = ProcessStep(title="Value Added", caption="AI Applications")
    # r = streamlit_app(extra_steps=[ai_step])
    # if r.selected_step == 4:
    #     st.write("🚧 Work in progress...")
