"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { ApiError, api, type Page } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  Dialog,
  ErrorText,
  Field,
  Input,
  Loading,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui";

type Room = {
  id: string;
  code: string;
  building: string | null;
  floor: number | null;
  capacity: number | null;
  room_type: "lecture" | "lab" | "seminar" | "online";
  lat: string | null;
  lon: string | null;
  gps_radius_m: number;
};

const ROOM_TYPES = ["lecture", "lab", "seminar", "online"] as const;

const schema = z
  .object({
    code: z.string().min(1, "required"),
    building: z.string().optional(),
    floor: z.string().optional(),
    capacity: z.string().optional(),
    room_type: z.enum(ROOM_TYPES),
    lat: z.string().optional(),
    lon: z.string().optional(),
    gps_radius_m: z.coerce.number().int().min(10).max(1000),
  })
  .refine(
    (v) => Boolean(v.lat) === Boolean(v.lon),
    { message: "lat and lon must be set together", path: ["lat"] },
  );
type FormData = z.infer<typeof schema>;

export default function RoomsTab() {
  const [items, setItems] = useState<Room[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  async function load() {
    setErr(null);
    try {
      const r = await api<Page<Room>>("/rooms", { query: { limit: 200 } });
      setItems(r.items);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "load failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onDelete(id: string) {
    if (!confirm("Soft-delete this room?")) return;
    try {
      await api(`/rooms/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "delete failed");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-600">
          {items ? `${items.length} active rooms` : "—"}
        </p>
        <Button onClick={() => setOpen(true)}>Add room</Button>
      </div>
      {err && <ErrorText>{err}</ErrorText>}
      {!items && !err && <Loading />}
      {items && (
        <Card>
          <Table>
            <thead>
              <tr>
                <Th>Code</Th>
                <Th>Type</Th>
                <Th>Building</Th>
                <Th>Floor</Th>
                <Th>Capacity</Th>
                <Th>GPS</Th>
                <Th>Radius</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr>
                  <Td colSpan={8} className="text-center text-zinc-500">
                    No rooms yet.
                  </Td>
                </tr>
              )}
              {items.map((r) => (
                <tr key={r.id}>
                  <Td className="font-mono text-xs">{r.code}</Td>
                  <Td className="capitalize">{r.room_type}</Td>
                  <Td>{r.building ?? "—"}</Td>
                  <Td>{r.floor ?? "—"}</Td>
                  <Td>{r.capacity ?? "—"}</Td>
                  <Td>
                    {r.lat && r.lon ? (
                      <Badge tone="green">set</Badge>
                    ) : (
                      <Badge>none</Badge>
                    )}
                  </Td>
                  <Td>{r.gps_radius_m}m</Td>
                  <Td className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onDelete(r.id)}
                    >
                      Delete
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <CreateDialog
        open={open}
        onClose={() => setOpen(false)}
        onCreated={async () => {
          setOpen(false);
          await load();
        }}
      />
    </div>
  );
}

function CreateDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      code: "",
      building: "",
      floor: "",
      capacity: "",
      room_type: "lecture",
      lat: "",
      lon: "",
      gps_radius_m: 100,
    },
  });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      reset();
      setErr(null);
    }
  }, [open, reset]);

  const onSubmit = handleSubmit(async (v) => {
    setErr(null);
    const body: Record<string, unknown> = {
      code: v.code,
      room_type: v.room_type,
      gps_radius_m: v.gps_radius_m,
    };
    if (v.building) body.building = v.building;
    if (v.floor) body.floor = Number(v.floor);
    if (v.capacity) body.capacity = Number(v.capacity);
    if (v.lat) body.lat = v.lat;
    if (v.lon) body.lon = v.lon;
    try {
      await api("/rooms", { method: "POST", body });
      await onCreated();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "create failed");
    }
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add room"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={isSubmitting}>
            {isSubmitting ? "Saving…" : "Save"}
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Code" error={errors.code?.message}>
            <Input placeholder="LH-201" {...register("code")} />
          </Field>
          <Field label="Type" error={errors.room_type?.message}>
            <Select {...register("room_type")}>
              {ROOM_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Building">
            <Input {...register("building")} />
          </Field>
          <Field label="Floor">
            <Input type="number" {...register("floor")} />
          </Field>
          <Field label="Capacity">
            <Input type="number" {...register("capacity")} />
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Latitude" error={errors.lat?.message}>
            <Input placeholder="12.943000" {...register("lat")} />
          </Field>
          <Field label="Longitude" error={errors.lon?.message}>
            <Input placeholder="77.563000" {...register("lon")} />
          </Field>
          <Field label="GPS radius (m)" error={errors.gps_radius_m?.message}>
            <Input type="number" {...register("gps_radius_m")} />
          </Field>
        </div>
        <ErrorText>{err}</ErrorText>
      </form>
    </Dialog>
  );
}
