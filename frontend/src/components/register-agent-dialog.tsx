"use client";

import { useState, useEffect, useRef } from "react";
import { X } from "lucide-react";

interface RegisterAgentDialogProps {
  open: boolean;
  onClose: () => void;
  onRegister: (name: string, endpointUrl: string, endpointType: string, description?: string) => Promise<void>;
}

export function RegisterAgentDialog({ open, onClose, onRegister }: RegisterAgentDialogProps) {
  const [name, setName] = useState("");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [endpointType, setEndpointType] = useState("supervisor");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameTouched = useRef(false);

  useEffect(() => {
    if (!open) {
      setName("");
      setEndpointUrl("");
      setEndpointType("supervisor");
      setDescription("");
      setError(null);
      setSubmitting(false);
      nameTouched.current = false;
    }
  }, [open]);

  const handleEndpointChange = (url: string) => {
    setEndpointUrl(url);
    if (!nameTouched.current) {
      const segments = url.split("/").filter(Boolean);
      const idx = segments.indexOf("serving-endpoints");
      const nameFromUrl = idx >= 0 && segments[idx + 1]
        ? segments[idx + 1].replace(/-/g, " ").replace(/_/g, " ")
        : segments[segments.length - 1]?.replace(/-/g, " ").replace(/_/g, " ") || "";
      if (nameFromUrl && nameFromUrl !== "invocations") {
        setName(nameFromUrl);
      }
    }
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    if (!endpointUrl.trim()) {
      setError("Endpoint URL is required");
      return;
    }
    try {
      new URL(endpointUrl);
    } catch {
      setError("Invalid URL format");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onRegister(name.trim(), endpointUrl.trim(), endpointType, description.trim());
      nameTouched.current = false;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Registration failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-background rounded-lg shadow-lg w-[400px] max-w-[90vw] p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Register New Agent</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted transition-colors">
            <X className="size-4" />
          </button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium mb-1.5">Name</label>
            <input
              value={name}
              onChange={(e) => { setName(e.target.value); nameTouched.current = true; }}
              placeholder="e.g., TPO Supervisor"
              className="w-full px-3 py-2 text-sm rounded-md border border-input bg-background focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium mb-1.5">Endpoint URL *</label>
            <input
              value={endpointUrl}
              onChange={(e) => handleEndpointChange(e.target.value)}
              placeholder="https://adb-.../serving-endpoints/name/invocations"
              className="w-full px-3 py-2 text-sm rounded-md border border-input bg-background focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium mb-1.5">Type</label>
            <select
              value={endpointType}
              onChange={(e) => setEndpointType(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-md border border-input bg-background focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="supervisor">Supervisor</option>
              <option value="responses_agent">Responses Agent</option>
              <option value="chain">Chain</option>
              <option value="completion">Completion</option>
              <option value="chat">Chat</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium mb-1.5">Description (optional)</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of this agent..."
              className="w-full px-3 py-2 text-sm rounded-md border border-input bg-background focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          {error && (
            <p className="text-xs text-red-500 bg-red-500/10 px-3 py-2 rounded-md">{error}</p>
          )}
          <button
            onClick={handleSubmit}
            disabled={submitting || !name.trim() || !endpointUrl.trim()}
            className="w-full py-2.5 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? "Registering..." : "Register Agent"}
          </button>
        </div>
      </div>
    </div>
  );
}
