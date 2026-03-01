# Service Performance Tracking ERP

## Project Overview
A Django-based ERP system for a telecom/retail business to track employee service activities and retail inventory across multiple branches.

## Key Features
- **Role-Based Dashboards**: Custom views for Super Admin, Director, Manager, Telecom, Retail, and MultiChoice staff.
- **Telecom Tracking**: SIM registrations, swaps, and upgrades against branch targets with manager approval for excesses.
- **Retail Inventory**: Full lifecycle management from Branch Safe Stock to Staff Stock and final Sales.
- **MultiChoice Integration**:
    - Subscription recording with dynamic package selection (DSTV/GOTV).
    - Cost and Amount tracking.
    - Weekly commission reporting (Monday opening to Saturday closing balance).
- **Analytics**: Director-level insights with revenue, profit, and performance charts.
- **MTN Branding**: Consistent UI using MTN Nigeria brand colors.

## Technical Stack
- **Backend**: Django 5.0, Python 3.x
- **Database**: SQLite (Development)
- **Frontend**: Django Templates, CSS (MTN Branding), Chart.js

## Recent Changes
- Implemented MultiChoice dynamic package selection.
- Added MultiChoice weekly reporting and commission calculation.
- Restricted inventory sidebar to relevant roles (Telecom, Retail, Manager).
- Added `cost_price` to MultiChoice sales.
