import { queryOptions } from "@tanstack/react-query";
import { api } from "../api/client";
import { unwrap } from "../api/errors";

/**
 * One note and its ETag. The tag is kept with the note because every change to it (W5) sends it
 * back as `If-Match`, so the server can tell a stale screen from a current one.
 */
export const noteQuery = (id: string) =>
  queryOptions({
    queryKey: ["note", id],
    queryFn: async ({ signal }) => {
      const answer = await api.GET("/api/v1/notes/{note_id}", {
        params: { path: { note_id: id } },
        signal,
      });
      const note = unwrap(answer);
      return { note, etag: answer.response.headers.get("ETag") };
    },
  });
