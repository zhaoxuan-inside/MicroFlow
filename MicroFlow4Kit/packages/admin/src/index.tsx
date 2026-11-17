/** 平台管理共享页：用户 / 租户 / 项目 / 角色（三大支撑平台共挂 /platform/*）。
 *
 * 全部经统一网关分发（platform.* 场景）；权限由后端强制，前端以 PermissionGate
 * / useScope 镜像显隐，避免无权操作的无效交互。
 */
import "./i18n";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { dispatch } from "@microflow4kit/api";
import { PermissionGate, useScope } from "@microflow4kit/ui";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  Spinner,
  cn,
} from "@microflow4kit/ui";

const th = "px-4 py-2.5 text-left text-xs font-medium font-mono uppercase text-muted-foreground";
const td = "px-4 py-2.5 align-middle";

function useInvalidate() {
  const qc = useQueryClient();
  return (...keys: string[]) => {
    for (const key of keys) qc.invalidateQueries({ queryKey: [key] });
  };
}


// 治理写操作统一经 OPC_PLATFORM_GOVERNANCE_PIPELINE（MicroFlow 元管线）执行：
// 场景名去掉 platform. 前缀即动作名，载荷走 {action, payload} 信封。
const WRITE_SCENARIOS: Record<string, string> = {
  "tenants.create": "platform.tenants.create",
  "tenants.update": "platform.tenants.update",
  "tenants.status": "platform.tenants.status",
  "tenants.members.add": "platform.tenants.members.add",
  "tenants.members.set_role": "platform.tenants.members.set_role",
  "tenants.members.remove": "platform.tenants.members.remove",
  "projects.create": "platform.projects.create",
  "projects.update": "platform.projects.update",
  "projects.status": "platform.projects.status",
  "projects.members.add": "platform.projects.members.add",
  "projects.members.set_role": "platform.projects.members.set_role",
  "projects.members.remove": "platform.projects.members.remove",
  "roles.create": "platform.roles.create",
  "roles.update": "platform.roles.update",
  "roles.delete": "platform.roles.delete",
  "users.set_role": "platform.users.set_role",
  "users.set_active": "platform.users.set_active",
  "users.reset_password": "platform.users.reset_password",
};

async function mutate(action: string, payload: Record<string, unknown>) {
  const scenario = WRITE_SCENARIOS[action];
  if (!scenario) throw new Error(`未知的平台治理操作：${action}`);
  return dispatch(scenario, { action, payload });
}

async function run<T>(fn: () => Promise<T>): Promise<string | null> {
  try {
    await fn();
    return null;
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
}

interface RoleOption {
  role_id: string;
  scope: string;
  code: string;
  name: string;
  builtin: boolean;
  tenant_id?: string;
  permissions: string[];
}

function useRoles(scopeFilter?: string) {
  return useQuery({
    queryKey: ["platform", "roles", scopeFilter || "all"],
    queryFn: async () => {
      const data = await dispatch<{ roles: RoleOption[] }>(
        "platform.roles.list",
        scopeFilter ? { scope: scopeFilter } : {},
      );
      return data.roles;
    },
  });
}

function RoleSelect({
  roles,
  value,
  onChange,
  ariaLabel,
}: {
  roles: RoleOption[];
  value: string;
  onChange: (roleId: string) => void;
  ariaLabel: string;
}) {
  return (
    <Select
      aria-label={ariaLabel}
      className="h-8 text-xs"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {roles.map((r) => (
        <option key={r.role_id} value={r.role_id}>
          {r.name}
        </option>
      ))}
    </Select>
  );
}

// ===========================================================================
// 用户管理（平台级）
// ===========================================================================
interface PlatformUser {
  uid: string;
  email: string;
  nickname: string;
  role: string;
  account_type: string;
  is_active: boolean;
}

export function UsersPage() {
  const { t } = useTranslation("admin");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [resetUid, setResetUid] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const invalidate = useInvalidate();
  const list = useQuery({
    queryKey: ["platform", "users", q],
    queryFn: () => dispatch<{ users: PlatformUser[]; total: number }>("platform.users.list", { q, limit: 200 }),
  });

  const setRole = async (uid: string, role: string) => {
    const err = await run(() => mutate("users.set_role", { user_id: uid, role }));
    setError(err);
    if (!err) invalidate("platform", "users");
  };
  const setActive = async (uid: string, is_active: boolean) => {
    const err = await run(() => mutate("users.set_active", { user_id: uid, is_active }));
    setError(err);
    if (!err) invalidate("platform", "users");
  };
  const resetPassword = async (uid: string) => {
    const err = await run(() =>
      mutate("users.reset_password", { user_id: uid, new_password: newPassword }),
    );
    setError(err);
    if (!err) {
      setResetUid("");
      setNewPassword("");
      invalidate("platform", "users");
    }
  };

  return (
    <div>
      <PageHeader title={t("users.title")} description={t("users.description")} />
      <Card className="mb-4">
        <CardContent className="flex items-center gap-2 px-4 py-3">
          <Input
            placeholder={t("users.searchPlaceholder")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="h-8 max-w-xs text-xs"
          />
          {error && <span className="text-xs text-destructive">{error}</span>}
        </CardContent>
      </Card>
      <Card>
        {list.isPending ? (
          <div className="flex justify-center py-16"><Spinner /></div>
        ) : !list.data?.users?.length ? (
          <div className="p-5"><EmptyState title={t("users.noMatch")} /></div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left">
                <th className={th}>{t("ui:common.user")}</th>
                <th className={th}>{t("users.platformRole")}</th>
                <th className={th}>{t("ui:common.status")}</th>
                <th className={th}>{t("ui:common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.users.map((u) => (
                <tr key={u.uid} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                  <td className={td}>
                    <div className="font-medium">{u.nickname || u.email}</div>
                    <div className="text-xs text-muted-foreground">{u.nickname && u.nickname !== u.email ? `${u.email} · ` : ""}{u.uid}</div>
                  </td>
                  <td className={td}>
                    <select
                      aria-label={t("users.setStatusAria", { email: u.email })}
                      className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                      value={u.role}
                      onChange={(e) => setRole(u.uid, e.target.value)}
                    >
                      <option value="ADMIN">{t("users.roleAdmin")}</option>
                      <option value="MAKER">{t("users.roleMaker")}</option>
                      <option value="GUEST">{t("users.roleGuest")}</option>
                    </select>
                  </td>
                  <td className={td}>
                    {u.is_active ? <Badge tone="success">{t("ui:common.enable")}</Badge> : <Badge tone="destructive">{t("ui:common.disable")}</Badge>}
                  </td>
                  <td className={td}>
                    <div className="flex gap-2">
                      <Button variant="secondary" className="h-7 text-xs"
                        onClick={() => setActive(u.uid, !u.is_active)}>
                        {u.is_active ? t("ui:common.disable") : t("ui:common.enable")}
                      </Button>
                      <Button variant="secondary" className="h-7 text-xs"
                        onClick={() => setResetUid(resetUid === u.uid ? "" : u.uid)}>
                        {t("users.resetPassword")}
                      </Button>
                    </div>
                    {resetUid === u.uid && (
                      <div className="mt-2 flex items-center gap-2">
                        <Input
                          type="password"
                          placeholder={t("users.newPasswordPlaceholder")}
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          className="h-8 max-w-[180px] text-xs"
                        />
                        <Button className="h-7 text-xs" onClick={() => resetPassword(u.uid)}>{t("ui:common.confirm")}</Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

// ===========================================================================
// 租户管理
// ===========================================================================
interface TenantRow {
  tenant_id: string;
  code: string;
  name: string;
  status: string;
  description: string;
}

interface TenantMember {
  binding_id: string;
  user_id: string;
  email: string;
  nickname: string;
  role_id: string;
  role_name: string;
}

export function TenantsPage() {
  const { t } = useTranslation("admin");
  const { hasPermission } = useScope();
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const [openMembers, setOpenMembers] = useState("");
  const invalidate = useInvalidate();
  const canManage = hasPermission("platform:tenant_manage");

  const tenants = useQuery({
    queryKey: ["platform", "tenants"],
    queryFn: () => dispatch<{ tenants: TenantRow[]; total: number }>("platform.tenants.list", {}),
  });
  const tenantRoles = useRoles("TENANT");

  const create = async () => {
    const err = await run(() => mutate("tenants.create", form));
    setError(err);
    if (!err) {
      setForm({ code: "", name: "", description: "" });
      invalidate("platform", "tenants");
    }
  };
  const setStatus = async (tenant_id: string, status: string) => {
    const err = await run(() => mutate("tenants.status", { tenant_id, status }));
    setError(err);
    if (!err) invalidate("platform", "tenants");
  };

  return (
    <div>
      <PageHeader title={t("tenants.title")} description={t("tenants.description")} />
      {error && <div className="mb-3 text-xs text-destructive">{error}</div>}
      <PermissionGate permission="platform:tenant_manage">
        <Card className="mb-4">
          <CardHeader><CardTitle>{t("tenants.create")}</CardTitle></CardHeader>
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label={t("tenants.codeLabel")} hint={t("tenants.codeHint")}>
                <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} className="h-8 text-xs" />
              </Field>
              <Field label={t("common.name")}>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="h-8 text-xs" />
              </Field>
              <Field label={t("common.description")}>
                <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="h-8 text-xs" />
              </Field>
              <div className="flex items-end">
                <Button className="h-8 text-xs" onClick={create}>{t("tenants.submit")}</Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </PermissionGate>
      <Card>
        {tenants.isPending ? (
          <div className="flex justify-center py-16"><Spinner /></div>
        ) : !tenants.data?.tenants?.length ? (
          <div className="p-5"><EmptyState title={t("tenants.emptyTitle")} hint={canManage ? t("tenants.emptyManageHint") : t("tenants.emptyViewHint")} /></div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left">
                <th className={th}>{t("ui:common.tenant")}</th>
                <th className={th}>{t("ui:common.status")}</th>
                <th className={th}>{t("ui:common.members")}</th>
                {canManage && <th className={th}>{t("ui:common.actions")}</th>}
              </tr>
            </thead>
            <tbody>
              {tenants.data.tenants.map((tenant) => (
                <tr key={tenant.tenant_id} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                  <td className={td}>
                    <div className="font-medium">{tenant.name}</div>
                    {(tenant.code !== tenant.name || tenant.description) && (
                      <div className="text-xs text-muted-foreground">
                        {tenant.code !== tenant.name
                          ? `${tenant.code}${tenant.description ? ` · ${tenant.description}` : ""}`
                          : tenant.description}
                      </div>
                    )}
                  </td>
                  <td className={td}>
                    {tenant.status === "ACTIVE" ? <Badge tone="success">{t("ui:common.enable")}</Badge> : <Badge tone="warning">{t("ui:common.disable")}</Badge>}
                  </td>
                  <td className={td}>
                    <Button variant="secondary" className="h-7 text-xs"
                      onClick={() => setOpenMembers(openMembers === tenant.tenant_id ? "" : tenant.tenant_id)}>
                      {t("ui:common.members")}
                    </Button>
                  </td>
                  {canManage && (
                    <td className={td}>
                      <Button variant="secondary" className="h-7 text-xs"
                        onClick={() => setStatus(tenant.tenant_id, tenant.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE")}>
                        {tenant.status === "ACTIVE" ? t("ui:common.disable") : t("ui:common.enable")}
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {openMembers && (
        <TenantMembersPanel
          tenantId={openMembers}
          roles={tenantRoles.data || []}
          canManage={canManage || hasPermission("tenant:member_manage")}
        />
      )}
    </div>
  );
}

function TenantMembersPanel({
  tenantId,
  roles,
  canManage,
}: {
  tenantId: string;
  roles: RoleOption[];
  canManage: boolean;
}) {
  const { t } = useTranslation("admin");
  const [error, setError] = useState<string | null>(null);
  const [account, setAccount] = useState("");
  const [roleId, setRoleId] = useState("");
  const invalidate = useInvalidate();
  const members = useQuery({
    queryKey: ["platform", "tenant-members", tenantId],
    queryFn: () => dispatch<{ members: TenantMember[] }>("platform.tenants.members.list", { tenant_id: tenantId }),
  });

  const add = async () => {
    const err = await run(() =>
      mutate("tenants.members.add", { tenant_id: tenantId, email: account, role_id: roleId || undefined }),
    );
    setError(err);
    if (!err) {
      setAccount("");
      invalidate("platform", "tenant-members");
    }
  };
  const setRole = async (userId: string, nextRole: string) => {
    const err = await run(() =>
      mutate("tenants.members.set_role", { tenant_id: tenantId, user_id: userId, role_id: nextRole }),
    );
    setError(err);
    if (!err) invalidate("platform", "tenant-members");
  };
  const remove = async (userId: string) => {
    const err = await run(() =>
      mutate("tenants.members.remove", { tenant_id: tenantId, user_id: userId }),
    );
    setError(err);
    if (!err) invalidate("platform", "tenant-members");
  };

  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>{t("tenants.panelTitle")}</CardTitle></CardHeader>
      <CardContent>
        {error && <div className="mb-2 text-xs text-destructive">{error}</div>}
        {canManage && (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Input placeholder={t("tenants.memberIdPlaceholder")} value={account} onChange={(e) => setAccount(e.target.value)} className="h-8 w-56 text-xs" />
            <RoleSelect roles={roles} value={roleId} onChange={setRoleId} ariaLabel={t("tenants.roleSelectAria")} />
            <Button className="h-8 text-xs" onClick={add}>{t("ui:common.addMember")}</Button>
          </div>
        )}
        {members.isPending ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : !members.data?.members?.length ? (
          <EmptyState title={t("ui:common.noMembers")} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left">
                <th className={th}>{t("ui:common.members")}</th>
                <th className={th}>{t("ui:common.role")}</th>
                {canManage && <th className={th}>{t("ui:common.actions")}</th>}
              </tr>
            </thead>
            <tbody>
              {members.data.members.map((m) => (
                <tr key={m.binding_id} className="border-b border-border/60 last:border-0">
                  <td className={td}>
                    <div className="font-medium">{m.nickname || m.email}</div>
                    {m.nickname && m.nickname !== m.email && (
                      <div className="text-xs text-muted-foreground">{m.email}</div>
                    )}
                  </td>
                  <td className={td}>
                    {canManage ? (
                      <RoleSelect roles={roles} value={m.role_id} onChange={(r) => setRole(m.user_id, r)} ariaLabel={t("tenants.adjustRoleAria", { email: m.email })} />
                    ) : (
                      <Badge>{m.role_name}</Badge>
                    )}
                  </td>
                  {canManage && (
                    <td className={td}>
                      <Button variant="destructive" className="h-7 text-xs" onClick={() => remove(m.user_id)}>{t("ui:common.remove")}</Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

// ===========================================================================
// 项目管理
// ===========================================================================
interface ProjectRow {
  project_id: string;
  tenant_id: string;
  key: string;
  name: string;
  status: string;
  description: string;
  my_role: string;
}

type ProjectMember = TenantMember;

export function ProjectsPage() {
  const { t } = useTranslation("admin");
  const { myScope, hasPermission } = useScope();
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ tenant_id: "", key: "", name: "", description: "" });
  const [openMembers, setOpenMembers] = useState("");
  const invalidate = useInvalidate();
  const canCreate = hasPermission("tenant:project_create");
  const canManageMembers = hasPermission("project:member_manage") || hasPermission("tenant:member_manage");

  const projects = useQuery({
    queryKey: ["platform", "projects"],
    queryFn: () => dispatch<{ projects: ProjectRow[] }>("platform.projects.list", {}),
  });
  const projectRoles = useRoles("PROJECT");

  const create = async () => {
    const err = await run(() => mutate("projects.create", form));
    setError(err);
    if (!err) {
      setForm({ tenant_id: "", key: "", name: "", description: "" });
      invalidate("platform", "projects");
    }
  };
  const setStatus = async (project_id: string, status: string) => {
    const err = await run(() => mutate("projects.status", { project_id, status }));
    setError(err);
    if (!err) invalidate("platform", "projects");
  };

  return (
    <div>
      <PageHeader title={t("projects.title")} description={t("projects.description")} />
      {error && <div className="mb-3 text-xs text-destructive">{error}</div>}
      {canCreate && (
        <Card className="mb-4">
          <CardHeader><CardTitle>{t("projects.create")}</CardTitle></CardHeader>
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label={t("projects.tenantLabel")}>
                <Select
                  aria-label={t("projects.tenantSelectAria")}
                  className="h-8 text-xs"
                  value={form.tenant_id}
                  onChange={(e) => setForm({ ...form, tenant_id: e.target.value })}
                >
                  <option value="">{t("projects.tenantPlaceholder")}</option>
                  {(myScope?.tenants || []).map((tenant) => (
                    <option key={tenant.tenant_id} value={tenant.tenant_id}>{tenant.name}</option>
                  ))}
                </Select>
              </Field>
              <Field label={t("projects.idLabel")} hint={t("projects.idHint")}>
                <Input value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} className="h-8 text-xs" />
              </Field>
              <Field label={t("common.name")}>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="h-8 text-xs" />
              </Field>
              <Field label={t("common.description")}>
                <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="h-8 text-xs" />
              </Field>
            </div>
            <div className="mt-4 flex justify-end">
              <Button className="h-8 text-xs" onClick={create}>{t("projects.submit")}</Button>
            </div>
          </CardContent>
        </Card>
      )}
      <Card>
        {projects.isPending ? (
          <div className="flex justify-center py-16"><Spinner /></div>
        ) : !projects.data?.projects?.length ? (
          <div className="p-5"><EmptyState title={t("projects.emptyTitle")} hint={t("projects.emptyHint")} /></div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left">
                <th className={th}>{t("ui:common.project")}</th>
                <th className={th}>{t("projects.myRole")}</th>
                <th className={th}>{t("ui:common.status")}</th>
                <th className={th}>{t("ui:common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {projects.data.projects.map((p) => (
                <tr key={p.project_id} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                  <td className={td}>
                    <div className="font-medium">{p.name}</div>
                    {(p.key !== p.name || p.description) && (
                      <div className="text-xs text-muted-foreground">
                        {p.key !== p.name
                          ? `${p.key}${p.description ? ` · ${p.description}` : ""}`
                          : p.description}
                      </div>
                    )}
                  </td>
                  <td className={td}>{p.my_role ? <Badge tone="primary">{p.my_role}</Badge> : <Badge>{t("projects.inTenant")}</Badge>}</td>
                  <td className={td}>
                    {p.status === "ACTIVE" ? <Badge tone="success">{t("projects.ongoing")}</Badge> : <Badge tone="warning">{t("projects.archived")}</Badge>}
                  </td>
                  <td className={td}>
                    <div className="flex gap-2">
                      <Button variant="secondary" className="h-7 text-xs"
                        onClick={() => setOpenMembers(openMembers === p.project_id ? "" : p.project_id)}>
                        {t("ui:common.members")}
                      </Button>
                      {hasPermission("project:manage") && (
                        <Button variant="secondary" className="h-7 text-xs"
                          onClick={() => setStatus(p.project_id, p.status === "ACTIVE" ? "ARCHIVED" : "ACTIVE")}>
                          {p.status === "ACTIVE" ? t("projects.archive") : t("projects.restore")}
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {openMembers && (
        <ProjectMembersPanel
          projectId={openMembers}
          roles={projectRoles.data || []}
          canManage={canManageMembers}
        />
      )}
    </div>
  );
}

function ProjectMembersPanel({
  projectId,
  roles,
  canManage,
}: {
  projectId: string;
  roles: RoleOption[];
  canManage: boolean;
}) {
  const { t } = useTranslation("admin");
  const [error, setError] = useState<string | null>(null);
  const [account, setAccount] = useState("");
  const [roleId, setRoleId] = useState("");
  const invalidate = useInvalidate();
  const members = useQuery({
    queryKey: ["platform", "project-members", projectId],
    queryFn: () => dispatch<{ members: ProjectMember[] }>("platform.projects.members.list", { project_id: projectId }),
  });

  const add = async () => {
    const err = await run(() =>
      mutate("projects.members.add", { project_id: projectId, email: account, role_id: roleId || undefined }),
    );
    setError(err);
    if (!err) {
      setAccount("");
      invalidate("platform", "project-members");
    }
  };
  const setRole = async (userId: string, nextRole: string) => {
    const err = await run(() =>
      mutate("projects.members.set_role", { project_id: projectId, user_id: userId, role_id: nextRole }),
    );
    setError(err);
    if (!err) invalidate("platform", "project-members");
  };
  const remove = async (userId: string) => {
    const err = await run(() =>
      mutate("projects.members.remove", { project_id: projectId, user_id: userId }),
    );
    setError(err);
    if (!err) invalidate("platform", "project-members");
  };

  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>{t("projects.panelTitle")}</CardTitle></CardHeader>
      <CardContent>
        {error && <div className="mb-2 text-xs text-destructive">{error}</div>}
        {canManage && (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Input placeholder={t("projects.memberIdPlaceholder")} value={account} onChange={(e) => setAccount(e.target.value)} className="h-8 w-64 text-xs" />
            <RoleSelect roles={roles} value={roleId} onChange={setRoleId} ariaLabel={t("projects.roleSelectAria")} />
            <Button className="h-8 text-xs" onClick={add}>{t("ui:common.addMember")}</Button>
          </div>
        )}
        {members.isPending ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : !members.data?.members?.length ? (
          <EmptyState title={t("ui:common.noMembers")} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50 text-left">
                <th className={th}>{t("ui:common.members")}</th>
                <th className={th}>{t("ui:common.role")}</th>
                {canManage && <th className={th}>{t("ui:common.actions")}</th>}
              </tr>
            </thead>
            <tbody>
              {members.data.members.map((m) => (
                <tr key={m.binding_id} className="border-b border-border/60 last:border-0">
                  <td className={td}>
                    <div className="font-medium">{m.nickname || m.email}</div>
                    {m.nickname && m.nickname !== m.email && (
                      <div className="text-xs text-muted-foreground">{m.email}</div>
                    )}
                  </td>
                  <td className={td}>
                    {canManage ? (
                      <RoleSelect roles={roles} value={m.role_id} onChange={(r) => setRole(m.user_id, r)} ariaLabel={t("projects.adjustRoleAria", { email: m.email })} />
                    ) : (
                      <Badge>{m.role_name}</Badge>
                    )}
                  </td>
                  {canManage && (
                    <td className={td}>
                      <Button variant="destructive" className="h-7 text-xs" onClick={() => remove(m.user_id)}>{t("ui:common.remove")}</Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

// ===========================================================================
// 角色管理（可配置 RBAC）
// ===========================================================================
interface PermissionItem {
  permission: string;
  builtin_role: string;
}

/** 权限点选择器：按前缀分组成网格，替代单行平铺（可读性 + 不撑爆容器）。 */
function PermissionPicker({
  permissions,
  checked,
  onToggle,
}: {
  permissions: PermissionItem[];
  checked: string[];
  onToggle: (permission: string, next: boolean) => void;
}) {
  const { t } = useTranslation("admin");
  const groups = new Map<string, string[]>();
  for (const p of permissions.map((x) => x.permission).sort()) {
    const key = p.includes(":") ? p.slice(0, p.indexOf(":")) : t("roles.groupOther");
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  return (
    <div>
      <div className="mb-2.5 text-xs text-muted-foreground">
        {t("roles.permissionsLabel")}{" "}
        <span className="font-medium text-foreground tabular-nums">{checked.length}</span>
        {" / "}
        <span className="tabular-nums">{permissions.length}</span>
      </div>
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-3">
        {[...groups.entries()].map(([group, items]) => (
          <div key={group} className="min-w-0">
            <div className="mb-1.5 text-[11px] font-medium text-muted-foreground/90">{group}</div>
            <div className="grid gap-1.5">
              {items.map((p) => (
                <label key={p} className="flex min-w-0 items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    className="accent-primary shrink-0"
                    checked={checked.includes(p)}
                    onChange={(e) => onToggle(p, e.target.checked)}
                  />
                  <span className="truncate text-foreground/90">{p}</span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RolesPage() {
  const { t } = useTranslation("admin");
  const { myScope, hasPermission } = useScope();
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ scope: "PROJECT", code: "", name: "", description: "" });
  const [checked, setChecked] = useState<string[]>([]);
  const [editing, setEditing] = useState("");
  const [editChecked, setEditChecked] = useState<string[]>([]);
  const [confirmRemove, setConfirmRemove] = useState<RoleOption | null>(null);
  const invalidate = useInvalidate();
  const canManage = hasPermission("platform:role_manage") || hasPermission("tenant:role_manage");

  const roles = useQuery({
    queryKey: ["platform", "roles", "manage"],
    queryFn: () => dispatch<{ roles: RoleOption[] }>("platform.roles.list", {}),
  });
  const permissions = useQuery({
    queryKey: ["platform", "permissions"],
    queryFn: () => dispatch<{ permissions: PermissionItem[] }>("platform.permissions.list", {}),
  });

  const create = async () => {
    const tenantId = myScope?.tenants[0]?.tenant_id || "";
    const err = await run(() =>
      mutate("roles.create", { ...form, tenant_id: tenantId, permissions: checked }),
    );
    setError(err);
    if (!err) {
      setForm({ scope: "PROJECT", code: "", name: "", description: "" });
      setChecked([]);
      invalidate("platform", "roles");
    }
  };
  const savePermissions = async (roleId: string) => {
    const err = await run(() =>
      mutate("roles.update", { role_id: roleId, permissions: editChecked }),
    );
    setError(err);
    if (!err) {
      setEditing("");
      invalidate("platform", "roles");
    }
  };
  const remove = async (role: RoleOption) => {
    const err = await run(() => mutate("roles.delete", { role_id: role.role_id }));
    setError(err);
    setConfirmRemove(null);
    if (!err) invalidate("platform", "roles");
  };

  return (
    <div>
      <PageHeader title={t("roles.title")} description={t("roles.description")} />
      {error && <div className="mb-3 text-xs text-destructive">{error}</div>}
      {canManage && (
        <Card className="mb-4">
          <CardHeader><CardTitle>{t("roles.create")}</CardTitle></CardHeader>
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label={t("roles.scopeLabel")}>
                <Select
                  aria-label={t("roles.scopeAria")}
                  className="h-8 text-xs"
                  value={form.scope}
                  onChange={(e) => setForm({ ...form, scope: e.target.value })}
                >
                  <option value="PROJECT">{t("ui:common.project")}</option>
                  <option value="TENANT">{t("ui:common.tenant")}</option>
                </Select>
              </Field>
              <Field label={t("roles.codeLabel")}>
                <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} className="h-8 text-xs" placeholder={t("roles.codePlaceholder")} />
              </Field>
              <Field label={t("ui:common.name")}>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="h-8 text-xs" placeholder={t("roles.namePlaceholder")} />
              </Field>
              <Field label={t("ui:common.description")}>
                <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="h-8 text-xs" placeholder={t("roles.descPlaceholder")} />
              </Field>
            </div>
            <div className="mt-4 rounded-md border border-border/70 bg-muted/40 px-4 py-3">
              <PermissionPicker
                permissions={permissions.data?.permissions ?? []}
                checked={checked}
                onToggle={(p, next) => setChecked(next ? [...checked, p] : checked.filter((x) => x !== p))}
              />
            </div>
            <div className="mt-4 flex justify-end">
              <Button className="h-8 text-xs" onClick={create}>{t("roles.submit")}</Button>
            </div>
          </CardContent>
        </Card>
      )}
      <Card>
        {roles.isPending ? (
          <div className="flex justify-center py-16"><Spinner /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50 text-left">
                  <th className={cn(th, "w-44")}>{t("ui:common.role")}</th>
                  <th className={cn(th, "w-16")}>{t("roles.headerScope")}</th>
                  <th className={th}>{t("roles.headerPermissions")}</th>
                  {canManage && <th className={cn(th, "w-44")}>{t("ui:common.actions")}</th>}
                </tr>
              </thead>
              <tbody>
                {(roles.data?.roles || []).map((r) => (
                  <tr key={r.role_id} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                    <td className={td}>
                      <div className="font-medium">{r.name}</div>
                      <div className="text-xs text-muted-foreground">{r.code}</div>
                    </td>
                    <td className={td}>
                      <Badge tone={r.scope === "PLATFORM" ? "primary" : r.scope === "TENANT" ? "warning" : "success"}>
                        {r.scope === "PLATFORM" ? t("roles.badgePlatform") : r.scope === "TENANT" ? t("roles.badgeTenant") : t("roles.badgeProject")}
                      </Badge>
                    </td>
                    <td className={cn(td, "min-w-0")}>
                      {r.permissions.includes("*") ? (
                        <Badge tone="primary">{t("roles.allPermissions")}</Badge>
                      ) : r.permissions.length ? (
                        <div className="flex max-w-3xl flex-wrap gap-1">
                          {r.permissions.map((p) => <Badge key={p} className="font-mono">{p}</Badge>)}
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">{t("ui:common.none")}</span>
                      )}
                    </td>
                    {canManage && (
                      <td className={td}>
                        {!r.builtin && (
                          <div className="flex gap-2">
                            <Button variant="secondary" className="h-7 text-xs"
                              onClick={() => {
                                setEditing(editing === r.role_id ? "" : r.role_id);
                                setEditChecked(r.permissions);
                              }}>
                              {t("roles.editButton")}
                            </Button>
                            <Button variant="destructive" className="h-7 text-xs" onClick={() => setConfirmRemove(r)}>
                              {t("ui:common.delete")}
                            </Button>
                          </div>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {editing && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>
              {t("roles.editTitle", { name: (roles.data?.roles ?? []).find((r) => r.role_id === editing)?.name || editing })}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <PermissionPicker
              permissions={permissions.data?.permissions ?? []}
              checked={editChecked}
              onToggle={(p, next) => setEditChecked(next ? [...editChecked, p] : editChecked.filter((x) => x !== p))}
            />
            <div className="mt-4 flex gap-2">
              <Button className="h-8 text-xs" onClick={() => savePermissions(editing)}>{t("ui:common.save")}</Button>
              <Button variant="secondary" className="h-8 text-xs" onClick={() => setEditing("")}>{t("ui:common.cancel")}</Button>
            </div>
          </CardContent>
        </Card>
      )}
      <ConfirmDialog
        open={confirmRemove !== null}
        title={t("roles.confirmTitle")}
        description={t("roles.confirmDescription", { name: confirmRemove?.name ?? "", code: confirmRemove?.code ?? "" })}
        onConfirm={() => confirmRemove && remove(confirmRemove)}
        onCancel={() => setConfirmRemove(null)}
      />
    </div>
  );
}
