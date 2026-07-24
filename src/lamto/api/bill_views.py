from django.urls import reverse
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import exceptions, generics, pagination
from rest_framework.response import Response
from rest_framework.views import APIView

from lamto.api.bill_serializers import BillDetailSerializer, BillSummarySerializer
from lamto.api.downloads import issue_download_token
from lamto.api.problems import problem_responses
from lamto.billing.models import Bill


class BillCursorPagination(pagination.CursorPagination):
    page_size = 20
    ordering = ("-issued_at", "-pk")


def _own_bills(user):
    return Bill.objects.filter(resident=user).exclude(status=Bill.Status.VOID)


def _detail_payload(request, bill):
    return {
        "id": bill.pk,
        "title": bill.title,
        "amount_vnd": bill.amount_vnd,
        "status": bill.status,
        "period": bill.period,
        "due_date": bill.due_date,
        "issued_at": bill.issued_at,
        "paid_at": bill.paid_at,
        "note": bill.note,
        "document_filename": bill.document.filename,
        "document_download_url": reverse(
            "api:document-download",
            args=[issue_download_token(request.user.pk, bill.document_id)],
        ),
    }


@extend_schema_view(
    get=extend_schema(
        operation_id="bills_list",
        tags=["bills"],
        responses={200: BillSummarySerializer(many=True), **problem_responses(401, 403)},
    )
)
class BillListView(generics.ListAPIView):
    serializer_class = BillSummarySerializer
    pagination_class = BillCursorPagination

    def get_queryset(self):
        return _own_bills(self.request.user)


class BillDetailView(APIView):
    @extend_schema(
        operation_id="bills_retrieve",
        tags=["bills"],
        responses={200: BillDetailSerializer, **problem_responses(401, 403, 404)},
    )
    def get(self, request, pk):
        bill = _own_bills(request.user).select_related("document").filter(pk=pk).first()
        if bill is None:
            raise exceptions.NotFound("Bill not found.")
        return Response(BillDetailSerializer(_detail_payload(request, bill)).data)
