"""Mock backend endpoints for Mission Control and Sales Command Center demos."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import cos, sin
from uuid import uuid4

from fastapi import APIRouter, Body, Query

router = APIRouter(tags=["command-center-mock"])


def _iso_date(days_delta: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days_delta)).date().isoformat()


def _series(days: int, base: int, variance: int) -> list[dict]:
    points = []
    for index in range(days):
        day_offset = index - days + 1
        wave = sin(index / 5) * variance
        trend = index * (variance / 12)
        points.append(
            {
                "date": _iso_date(day_offset),
                "value": max(0, round(base + trend + wave + (index % 6) * 3)),
                "secondary": max(0, round(base * 0.7 + trend * 0.8 + wave * 0.5)),
            }
        )
    return points


def _sales_series() -> list[dict]:
    return [
        {
            "date": _iso_date(index - 89),
            "value": round(12000 + index * 220 + sin(index / 4) * 1700),
            "secondary": round(9000 + index * 180 + cos(index / 5) * 1200),
        }
        for index in range(90)
    ]


INDUSTRIES = ["Healthcare", "Real Estate", "Legal", "Hospitality", "Finance", "Education", "Automotive", "Retail"]
PROVINCES = ["Ontario", "British Columbia", "California", "Texas", "New York", "Alberta", "Florida", "Washington"]
OWNERS = ["Ava Thompson", "Noah Patel", "Mia Chen", "Liam Brooks", "Sophia Rivera", "Ethan Wilson", "Olivia Singh", "Lucas Martin"]
PLANS = ["Starter", "Growth", "Scale", "Enterprise"]
STATUSES = ["Active", "Trial", "Active", "Active", "Suspended", "Cancelled", "Expired"]
AI_EMPLOYEES = ["Voice", "Marketing", "Sales", "HR", "Executive"]
COMPANY_NAMES = [
    "Northstar Dental Group",
    "Cedar Ridge Realty",
    "BrightPath Legal",
    "Summit Wellness Clinics",
    "Harborview Hotels",
    "Meridian Accounting",
    "Prairie Auto Sales",
    "Evergreen Education",
    "BluePeak Roofing",
    "Urban Table Hospitality",
    "Westlake Insurance",
    "Oak & Pine Realty",
    "Silverline Logistics",
    "Kindred Home Care",
    "Atlas Fitness Clubs",
    "Maple Grove Dental",
    "Frontier HVAC",
    "Beacon Mortgage",
    "Pacific Pet Care",
    "Redwood Legal Partners",
    "Clearwater Med Spa",
    "Vertex Accounting",
    "Momentum Auto Group",
    "Golden Gate Storage",
    "Lakeside Family Health",
]


def _companies() -> list[dict]:
    companies = []
    for index, name in enumerate(COMPANY_NAMES):
        account_status = STATUSES[index % len(STATUSES)]
        subscription_status = "Trial" if account_status == "Trial" else "Cancelled" if account_status == "Cancelled" else "Paid"
        health_score = max(34, min(98, 96 - (index % 9) * 7 + (index % 3) * 4))
        slug = "".join(char for char in name.lower() if char.isalnum())
        companies.append(
            {
                "id": f"company-{index + 1}",
                "name": name,
                "owner": OWNERS[index % len(OWNERS)],
                "email": f"admin@{slug}.com",
                "phone": f"+1 555 {210 + index:03d} {str(1100 + index * 37)[:4]}",
                "industry": INDUSTRIES[index % len(INDUSTRIES)],
                "country": "United States" if index % 5 == 0 else "Canada",
                "province": PROVINCES[index % len(PROVINCES)],
                "accountStatus": account_status,
                "subscriptionStatus": subscription_status,
                "plan": PLANS[index % len(PLANS)],
                "renewalDate": _iso_date(20 + index * 3),
                "createdDate": _iso_date(-(180 - index * 4)),
                "lastLogin": _iso_date(-(index % 15)),
                "activeUsers": 4 + (index % 8) * 3,
                "voiceMinutes": 420 + index * 137,
                "apiCalls": 8500 + index * 1940,
                "storageUsedGb": round(12 + index * 2.8, 1),
                "aiEmployees": [employee for agent_index, employee in enumerate(AI_EMPLOYEES) if (agent_index + index) % 2 == 0 or agent_index == 0],
                "healthScore": health_score,
                "mrr": [299, 599, 1299, 2499][index % 4],
            }
        )
    return companies


def _mission_dashboard() -> dict:
    companies = _companies()
    top_usage = sorted(companies, key=lambda company: company["apiCalls"] + company["voiceMinutes"], reverse=True)[:8]
    return {
        "companies": companies,
        "kpis": [
            {"title": "Total Companies", "value": "25", "change": "+8.2%", "changeType": "positive", "series": [12, 15, 16, 18, 20, 23, 25]},
            {"title": "Active Companies", "value": "18", "change": "+5.4%", "changeType": "positive", "series": [11, 12, 13, 15, 16, 17, 18]},
            {"title": "Trial Companies", "value": "4", "change": "+2 today", "changeType": "positive", "series": [2, 3, 2, 4, 3, 4, 4]},
            {"title": "MRR", "value": "$29.4K", "change": "+12.1%", "changeType": "positive", "series": [18, 20, 22, 24, 25, 27, 29]},
            {"title": "ARR", "value": "$352.8K", "change": "+10.8%", "changeType": "positive", "series": [240, 260, 280, 298, 315, 335, 352]},
            {"title": "Churn Rate", "value": "2.8%", "change": "-0.6%", "changeType": "positive", "series": [4.1, 3.9, 3.4, 3.2, 3, 2.9, 2.8]},
            {"title": "Active AI Employees", "value": "87", "change": "+14", "changeType": "positive", "series": [44, 50, 57, 65, 73, 81, 87]},
            {"title": "API Requests Today", "value": "182K", "change": "+18.7%", "changeType": "positive", "series": [120, 132, 148, 151, 160, 171, 182]},
        ],
        "signups": _series(90, 5, 4),
        "revenue": _series(90, 22000, 900),
        "apiUsage": _series(90, 82000, 9000),
        "voiceMinutes": _series(90, 4200, 600),
        "customerGrowth": _series(90, 12, 4),
        "topCompaniesByUsage": [
            {
                "name": company["name"],
                "usage": company["apiCalls"] + company["voiceMinutes"] * 12,
                "status": "healthy" if company["healthScore"] >= 75 else "attention" if company["healthScore"] >= 50 else "risk",
            }
            for company in top_usage
        ],
        "insights": [
            {"id": "insight-1", "title": "Three accounts show churn risk", "severity": "risk", "explanation": "Low login frequency and rising support tickets are pulling health scores below 55.", "recommendedAction": "Assign Customer Success follow-ups today"},
            {"id": "insight-2", "title": "Voice minutes outpacing plan limits", "severity": "attention", "explanation": "Five Growth customers are projected to exceed included voice minutes before renewal.", "recommendedAction": "Prepare usage upgrade offers"},
            {"id": "insight-3", "title": "Enterprise expansion opportunity", "severity": "healthy", "explanation": "High API adoption and stable usage suggest strong fit for Executive and HR agents.", "recommendedAction": "Create upsell campaign segment"},
        ],
    }


REPS = [
    {"id": "rep-1", "name": "Avery Stone", "role": "Sales Manager", "avatarFallback": "AS", "quotaAttainment": 118, "mrrClosed": 14800, "meetingsBooked": 17, "demosCompleted": 9, "attendanceStatus": "Present"},
    {"id": "rep-2", "name": "Priya Nair", "role": "Account Executive", "avatarFallback": "PN", "quotaAttainment": 94, "mrrClosed": 9200, "meetingsBooked": 13, "demosCompleted": 7, "attendanceStatus": "Present"},
    {"id": "rep-3", "name": "Marcus Lee", "role": "Account Executive", "avatarFallback": "ML", "quotaAttainment": 87, "mrrClosed": 7600, "meetingsBooked": 11, "demosCompleted": 6, "attendanceStatus": "Late"},
    {"id": "rep-4", "name": "Sofia Gomez", "role": "SDR", "avatarFallback": "SG", "quotaAttainment": 105, "mrrClosed": 6100, "meetingsBooked": 21, "demosCompleted": 8, "attendanceStatus": "Present"},
    {"id": "rep-5", "name": "Daniel Kim", "role": "SDR", "avatarFallback": "DK", "quotaAttainment": 76, "mrrClosed": 4800, "meetingsBooked": 14, "demosCompleted": 5, "attendanceStatus": "Present"},
    {"id": "rep-6", "name": "Nora Brooks", "role": "Account Executive", "avatarFallback": "NB", "quotaAttainment": 69, "mrrClosed": 3900, "meetingsBooked": 8, "demosCompleted": 4, "attendanceStatus": "Absent"},
]
SALES_COMPANIES = COMPANY_NAMES + ["Summit Title Services", "Greenfield Insurance", "Apollo Med Spa", "Cobalt Legal", "Pinecrest Clinics", "Signal Realty", "Juniper HVAC", "Riverstone Dental", "Noble Auto Center", "Peak Hospitality", "Bridgeview Finance", "MetroFit Studios", "TrueNorth Logistics", "Anchor Mortgage", "Bluebird Education"]
STAGES = ["Discovery", "Demo Scheduled", "Proposal", "Negotiation", "Closing"]
RISKS = ["healthy", "attention", "risk", "healthy", "attention"]


def _pipeline_deals() -> list[dict]:
    return [
        {
            "id": f"deal-{index + 1}",
            "company": company,
            "owner": REPS[index % len(REPS)]["name"],
            "value": 2200 + (index % 8) * 1850 + index * 120,
            "stage": STAGES[index % len(STAGES)],
            "decisionMaker": ["CEO", "Operations Director", "Revenue Lead", "Practice Owner", "Managing Partner"][index % 5],
            "nextStep": ["Book technical demo", "Send ROI calculator", "Confirm decision timeline", "Review pricing", "Loop in implementation lead"][index % 5],
            "closeDate": _iso_date(3 + (index % 18)),
            "riskLevel": RISKS[index % len(RISKS)],
            "aiCloseProbability": max(28, min(94, 82 - (index % 7) * 6 + (index % 4) * 5)),
        }
        for index, company in enumerate(SALES_COMPANIES)
    ]


def _sales_dashboard() -> dict:
    return {
        "reps": REPS,
        "deals": _pipeline_deals(),
        "revenueSeries": _sales_series(),
        "cards": [
            {"title": "Today's Meeting", "value": "Monday Kick-Off", "change": "Starts 9:30 AM", "status": "healthy"},
            {"title": "Team Attendance", "value": "5 / 6", "change": "1 absent", "status": "attention"},
            {"title": "Weekly MRR Goal", "value": "$42K", "change": "62% forecast", "status": "attention"},
            {"title": "MRR Closed This Week", "value": "$26.4K", "change": "+18% vs last week", "status": "healthy"},
            {"title": "Meetings Booked", "value": "84", "change": "+11 booked today", "status": "healthy"},
            {"title": "Pipeline Value", "value": "$356K", "change": "40 active deals", "status": "healthy"},
            {"title": "Demos Completed", "value": "39", "change": "8 this week", "status": "healthy"},
            {"title": "Quota Attainment", "value": "91%", "change": "Team average", "status": "attention"},
        ],
        "meetings": [
            {"id": "monday", "title": "Monday Kick-Off", "cadence": "Weekly", "time": "Today 9:30 AM", "status": "Today", "description": "Commitments, pipeline review, coaching focus, and weekly priorities.", "pendingItems": 7},
            {"id": "daily", "title": "Daily Stand-Up", "cadence": "Daily", "time": "Tomorrow 9:15 AM", "status": "Upcoming", "description": "Wins, activities, priorities, movement, roadblocks, and AI brief.", "pendingItems": 4},
            {"id": "friday", "title": "Friday Review", "cadence": "Weekly", "time": "Friday 3:30 PM", "status": "Upcoming", "description": "Celebrate wins, compare results to goals, analyze lost deals, and commit improvements.", "pendingItems": 5},
            {"id": "monthly", "title": "Monthly Sales Intelligence", "cadence": "Monthly", "time": "Aug 30 10:00 AM", "status": "Upcoming", "description": "Executive revenue, funnel, customer, market, conversation, and product intelligence.", "pendingItems": 11},
        ],
        "actionItems": [
            {"id": "action-1", "title": "Escalate Redwood Legal pricing concern", "owner": "Priya Nair", "dueDate": _iso_date(1), "status": "In Progress", "priority": "risk"},
            {"id": "action-2", "title": "Prepare HVAC objection handling practice", "owner": "Avery Stone", "dueDate": _iso_date(2), "status": "Open", "priority": "attention"},
            {"id": "action-3", "title": "Send case study to Harborview Hotels", "owner": "Marcus Lee", "dueDate": _iso_date(1), "status": "Open", "priority": "healthy"},
            {"id": "action-4", "title": "Confirm technical buyer for Bridgeview Finance", "owner": "Nora Brooks", "dueDate": _iso_date(3), "status": "Blocked", "priority": "risk"},
        ],
    }


def _monday_kickoff() -> dict:
    deals = _pipeline_deals()
    return {
        "lastWeekPerformance": [
            {"label": "New customers closed", "value": "9", "delta": "+3 vs prior week"},
            {"label": "New MRR", "value": "$26.4K", "delta": "+18%"},
            {"label": "Pipeline created", "value": "$88K", "delta": "+11%"},
            {"label": "Meetings booked", "value": "84", "delta": "+9%"},
            {"label": "Demo conversion", "value": "42%", "delta": "+4.2 pts"},
            {"label": "Quota attainment", "value": "91%", "delta": "+6 pts"},
        ],
        "pipelineReview": [deal for deal in deals if deal["stage"] in {"Proposal", "Negotiation"} or deal["riskLevel"] != "healthy"][:12],
        "weeklyTargets": [
            {"rep": rep["name"], "outboundTouches": 120 + index * 10, "meetings": 8 + index, "demos": 4 + (index % 3), "customers": 1 + (index % 2), "mrrTarget": 4500 + index * 900}
            for index, rep in enumerate(REPS)
        ],
        "campaigns": [
            {"title": "Dental AI Voice Sprint", "detail": "Prioritize multi-location dental groups with missed-call pain.", "owner": "Sofia Gomez"},
            {"title": "Legal Intake Automation", "detail": "Use new intake ROI calculator for managing partners.", "owner": "Priya Nair"},
            {"title": "Hospitality Summer Recovery", "detail": "Lead with abandoned booking follow-up and SMS reminders.", "owner": "Marcus Lee"},
        ],
        "coaching": [
            {"topic": "Pricing objection", "suggestion": "Anchor on recovered appointments before platform cost.", "priority": "attention"},
            {"topic": "Demo discovery", "suggestion": "Ask for current missed-call volume before showing voice workflow.", "priority": "healthy"},
            {"topic": "Technical buyer alignment", "suggestion": "Add integration owner by proposal stage for all Scale deals.", "priority": "risk"},
        ],
    }


@router.get("/sales-command-center/dashboard")
async def get_sales_command_center_dashboard(business_id: str | None = Query(default=None)):
    return _sales_dashboard()


@router.get("/sales-command-center/monday-kickoff")
async def get_sales_command_center_monday_kickoff(business_id: str | None = Query(default=None)):
    return _monday_kickoff()


@router.post("/sales-command-center/monday-kickoff/report")
async def generate_monday_kickoff_report(payload: dict | None = Body(default=None)):
    return {
        "id": f"mock-report-{uuid4()}",
        "status": "generated",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "summary": "Weekly commitments, action items, pipeline changes, and coaching topics were generated from mock backend data.",
        "meetingType": (payload or {}).get("meetingType", "monday-kickoff"),
    }
