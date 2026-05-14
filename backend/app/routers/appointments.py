import logging
from fastapi import APIRouter, Depends
from app.core.auth import get_user_id, require_business_access
from app.schemas.appointments import (
    CreateAppointmentRequest,
    UpdateAppointmentRequest,
    AppointmentResponse,
    CancelAppointmentResponse,
)
from app.services import booking_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentResponse)
async def create_appointment(
    body: CreateAppointmentRequest,
    user_id: str = Depends(get_user_id),
    _: str = Depends(require_business_access()),
):
    return await booking_service.create_appointment(body, created_by=user_id)


@router.put("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    appointment_id: str,
    body: UpdateAppointmentRequest,
    _: str = Depends(get_user_id),
    __: str = Depends(require_business_access()),
):
    return await booking_service.update_appointment(appointment_id, body)


@router.delete("/{appointment_id}", response_model=CancelAppointmentResponse)
async def cancel_appointment(
    appointment_id: str,
    business_id: str,
    _: str = Depends(get_user_id),
    __: str = Depends(require_business_access()),
):
    return await booking_service.cancel_appointment(appointment_id, business_id)
