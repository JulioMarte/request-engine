/* eslint-disable */
/**
 * Generated `api` utility.
 *
 * THIS CODE IS AUTOMATICALLY GENERATED.
 *
 * To regenerate, run `npx convex dev`.
 * @module
 */

import type * as aiStates from "../aiStates.js";
import type * as catalog from "../catalog.js";
import type * as crons from "../crons.js";
import type * as domainValidators from "../domainValidators.js";
import type * as http from "../http.js";
import type * as knowledge from "../knowledge.js";
import type * as lib_confirmationPolicy from "../lib/confirmationPolicy.js";
import type * as lib_errors from "../lib/errors.js";
import type * as lib_ids from "../lib/ids.js";
import type * as lib_time from "../lib/time.js";
import type * as openapi from "../openapi.js";
import type * as tenants from "../tenants.js";
import type * as v1AgentAuth from "../v1AgentAuth.js";
import type * as v1Availability from "../v1Availability.js";
import type * as v1Bookings from "../v1Bookings.js";
import type * as v1Callbacks from "../v1Callbacks.js";
import type * as v1Catalog from "../v1Catalog.js";
import type * as v1Dashboard from "../v1Dashboard.js";
import type * as v1Holidays from "../v1Holidays.js";
import type * as v1Insurance from "../v1Insurance.js";
import type * as v1Organizations from "../v1Organizations.js";
import type * as v1Outbox from "../v1Outbox.js";
import type * as v1People from "../v1People.js";
import type * as v1Provisioning from "../v1Provisioning.js";
import type * as v1Queue from "../v1Queue.js";
import type * as v1Runtime from "../v1Runtime.js";
import type * as v1Waitlist from "../v1Waitlist.js";

import type {
  ApiFromModules,
  FilterApi,
  FunctionReference,
} from "convex/server";

declare const fullApi: ApiFromModules<{
  aiStates: typeof aiStates;
  catalog: typeof catalog;
  crons: typeof crons;
  domainValidators: typeof domainValidators;
  http: typeof http;
  knowledge: typeof knowledge;
  "lib/confirmationPolicy": typeof lib_confirmationPolicy;
  "lib/errors": typeof lib_errors;
  "lib/ids": typeof lib_ids;
  "lib/time": typeof lib_time;
  openapi: typeof openapi;
  tenants: typeof tenants;
  v1AgentAuth: typeof v1AgentAuth;
  v1Availability: typeof v1Availability;
  v1Bookings: typeof v1Bookings;
  v1Callbacks: typeof v1Callbacks;
  v1Catalog: typeof v1Catalog;
  v1Dashboard: typeof v1Dashboard;
  v1Holidays: typeof v1Holidays;
  v1Insurance: typeof v1Insurance;
  v1Organizations: typeof v1Organizations;
  v1Outbox: typeof v1Outbox;
  v1People: typeof v1People;
  v1Provisioning: typeof v1Provisioning;
  v1Queue: typeof v1Queue;
  v1Runtime: typeof v1Runtime;
  v1Waitlist: typeof v1Waitlist;
}>;

/**
 * A utility for referencing Convex functions in your app's public API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = api.myModule.myFunction;
 * ```
 */
export declare const api: FilterApi<
  typeof fullApi,
  FunctionReference<any, "public">
>;

/**
 * A utility for referencing Convex functions in your app's internal API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = internal.myModule.myFunction;
 * ```
 */
export declare const internal: FilterApi<
  typeof fullApi,
  FunctionReference<any, "internal">
>;

export declare const components: {};
