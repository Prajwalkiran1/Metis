"use client";

import { useState } from "react";
import { Tabs } from "@/components/ui";
import DepartmentsTab from "./_tabs/departments";
import CoursesTab from "./_tabs/courses";
import BatchesTab from "./_tabs/batches";
import RoomsTab from "./_tabs/rooms";
import TimetableTab from "./_tabs/timetable";
import CalendarTab from "./_tabs/calendar";

const TABS = [
  { id: "departments", label: "Departments" },
  { id: "courses", label: "Courses" },
  { id: "batches", label: "Batches" },
  { id: "rooms", label: "Rooms" },
  { id: "timetable", label: "Timetable" },
  { id: "calendar", label: "Calendar" },
];

export default function AcademicPage() {
  const [active, setActive] = useState("departments");

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-zinc-900">Academic</h1>
        <p className="text-xs text-zinc-500">
          Manage departments, courses, batches, sections, rooms, timetable,
          and academic calendar.
        </p>
      </div>
      <Tabs tabs={TABS} active={active} onChange={setActive} />
      <div className="pt-2">
        {active === "departments" && <DepartmentsTab />}
        {active === "courses" && <CoursesTab />}
        {active === "batches" && <BatchesTab />}
        {active === "rooms" && <RoomsTab />}
        {active === "timetable" && <TimetableTab />}
        {active === "calendar" && <CalendarTab />}
      </div>
    </div>
  );
}
