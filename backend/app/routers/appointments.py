import logging
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_user_id, verify_business_access, require_business_access
from app.core.supabase import supabase_admin
from app.schemas.appointments import (
    CreateAppointmentRequest,
    UpdateAppointmentRequest,
    UpdateAppointmentStatusRequest,
    AppointmentResponse,
    CancelAppointmentResponse,
    VALID_APPOINTMENT_STATUSES,
)
from app.services import booking_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentResponse)
async def create_appointment(
    body: CreateAppointmentRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    return await booking_service.create_appointment(body, created_by=user_id)


@router.put("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    appointment_id: str,
    body: UpdateAppointmentRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    return await booking_service.update_appointment(appointment_id, body)


@router.patch("/{appointment_id}/status")
async def update_appointment_status(
    appointment_id: str,
    body: UpdateAppointmentStatusRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    if body.status not in VALID_APPOINTMENT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_APPOINTMENT_STATUSES))}",
        )
    result = (
        supabase_admin.table("appointments")
        .update({"status": body.status})
        .eq("id", appointment_id)
        .eq("business_id", body.business_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return result.data[0]


@router.delete("/{appointment_id}", response_model=CancelAppointmentResponse)
async def cancel_appointment(
    appointment_id: str,
    business_id: str,
    _: str = Depends(require_business_access()),
    user_id: str = Depends(get_user_id),
):
    return await booking_service.cancel_appointment(appointment_id, business_id)
