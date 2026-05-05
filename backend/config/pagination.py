from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


class UnboundedPagination(PageNumberPagination):
    # Returns the full result set in a single response while preserving the
    # standard {count, next, previous, results} shape so existing typed
    # frontend clients keep working. Use only on endpoints whose result set
    # is bounded by domain reality (e.g. memberships on a single tenant
    # entity), where pagination would risk silent truncation at the page
    # boundary without any operational benefit.
    page_size = 10000
    page_size_query_param = None
    max_page_size = 10000
