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
- **Database**: SQLite (Development), indexed queries for performance
- **Frontend**: Django Templates, CSS (MTN Branding), Chart.js, Responsive Design
- **Reporting**: ReportLab for PDF generation
- **Security**: Role-based decorators, CSRF protection, branch-level data isolation
- **Email**: SMTP configured for automated reporting (ready to deploy)

## Deployed Features
- **Attendance Tracking**: GPS check-in/check-out, geofencing, selfie capture, late detection (₦250), absence flagging
- **Branch Location Management**: Director can configure GPS coordinates and radius for each branch
- **Attendance Dashboards**: Staff history, director analytics with PDF export
- **Multi-Role Support**: Attendance features visible on all staff dashboards (TELECOM, RETAIL, MULTICHOICE, MANAGER)
- **Role-Based Access Control**: Directors only access to attendance analytics and branch configuration

## Recent Changes (Latest Round)
- **Login UI Enhanced**: Added password visibility toggle with eye icon (👁️), improved styling with MTN branding, better form validation and error display
- **Dashboard Text Visibility**: Fixed manager dashboard to use dark text colors (#333) for better readability on white backgrounds
- **Telecom Staff Services**: Added Router Sale and Wholesale SIM as physical product sales (not device-tag-dependent) alongside Mifi Sales
- **Director Safe Stock**: New feature allowing directors to manage stock not yet distributed to branches. Full CRUD operations with product selection, quantity tracking, and deletion
- **Service Options Expanded**: Updated ServiceActivity model to support ROUTER and WHOLESALE_SIM service types

## Earlier Changes
- **Attendance Tracking System**: Implemented GPS-based check-in/check-out with geofencing (100m radius), selfie capture, automatic late detection (₦250 deduction), and absence flagging. Features include time-window validation (7:30-8:00 AM weekdays, 9:00-9:15 AM Saturdays), distance calculation via Haversine formula, attendance history dashboard, director analytics dashboard, and PDF monthly report export. Automated absent staff alerts at 8:30 AM daily.
- **Media Handling**: Added Pillow and ReportLab packages; configured MEDIA_URL and MEDIA_ROOT for image uploads (attendance selfies).
- **Branch Geo-Data**: Updated Branch model with latitude, longitude, allowed_radius (default 100m), and location_locked fields.
- **Authentication Fix**: Fixed login logic to properly authenticate all user roles (Manager, Director, Retail, MultiChoice, Telecom, Superadmin); added `user_logout` view; fixed redirect loops.
- **URL Routing**: Added missing logout URL; mapped telecom_dashboard to staff_dashboard; corrected all role-based redirects; added attendance routes.
- **UI Production Polish**: Redesigned base.html with modern MTN-branded header, collapsible sidebar, responsive footer, and loading spinner.
- **Security Enhancements**: Added `@role_required` decorator for all dashboard views; locked cost price editing to Directors only; enforced branch-level data isolation.
- **Reporting Features**: Implemented PDF export for managers (daily retail reports) and directors (branch summary reports); added manager retail sales filtering by product/staff.
- **Database Optimization**: Added indexes to RetailSale (date, branch, staff) for performance; configured email backend for future automated reporting.
- **Inventory Management**: Full IMEI tracking, payment method recording on sales, stock request workflow, expense tracking with net profit calculation.
- **MultiChoice**: Dynamic package selection (DSTV/GOTV), weekly reporting with auto-calculated commissions, cost tracking.
