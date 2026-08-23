/** Contract-typed Public Service API client. */
import createClient, { type Client } from "openapi-fetch";

import type { paths } from "./schema.gen";

export type PublicServiceClient = Client<paths>;

export const createPublicServiceClient = (baseUrl = ""): PublicServiceClient =>
  createClient<paths>({
    baseUrl,
    credentials: "same-origin",
  });
