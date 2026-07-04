-- ============================================================================
--  Assistant radiologue virtuel — schéma Supabase
--  À exécuter dans Supabase : SQL Editor > New query > coller > Run.
--  Crée : rôles, profils, patients, scans, politiques RLS, bucket d'images.
-- ============================================================================

-- --- Type de rôle -----------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_type where typname = 'user_role') then
    create type user_role as enum ('admin', 'doctor');
  end if;
end$$;

-- --- Profils (étend auth.users) --------------------------------------------
create table if not exists public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  full_name   text not null default '',
  role        user_role not null default 'doctor',
  created_at  timestamptz not null default now()
);

-- --- Patients ---------------------------------------------------------------
create table if not exists public.patients (
  id            uuid primary key default gen_random_uuid(),
  external_ref  text,                         -- n° dossier interne
  full_name     text not null,
  email         text,                         -- pour la notification de création
  birth_date    date,
  sex           text check (sex in ('F', 'M', 'other') or sex is null),
  notes         text,
  created_by    uuid references public.profiles(id),
  created_at    timestamptz not null default now()
);
-- Migration douce si la table existait déjà sans la colonne email :
alter table public.patients add column if not exists email text;

-- --- Scans (résultat d'analyse d'une radio) --------------------------------
create table if not exists public.scans (
  id               uuid primary key default gen_random_uuid(),
  patient_id       uuid not null references public.patients(id) on delete cascade,
  image_path       text,                      -- chemin dans le bucket 'radios'
  predicted_class  text,
  confidence       numeric,
  image_quality    text,
  model_name       text,
  result_json      jsonb,                     -- sortie complète du modèle
  reviewed         boolean not null default false,   -- validé par un médecin
  uploaded_by      uuid references public.profiles(id),
  created_at       timestamptz not null default now()
);

create index if not exists scans_patient_idx on public.scans(patient_id);
create index if not exists scans_created_idx on public.scans(created_at desc);

-- --- Journal d'audit (traçabilité des actions sensibles) -------------------
create table if not exists public.audit_log (
  id          uuid primary key default gen_random_uuid(),
  actor_id    uuid references public.profiles(id),
  action      text not null,
  entity      text,
  entity_id   text,
  meta        jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists audit_created_idx on public.audit_log(created_at desc);

-- --- Création automatique du profil à l'inscription ------------------------
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, full_name, role)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name', ''), 'doctor')
  on conflict (id) do nothing;
  return new;
end$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============================================================================
--  Row Level Security
--  Modèle "clinique" : tout utilisateur authentifié voit les patients et scans
--  de la structure ; seul un admin gère les rôles des utilisateurs.
-- ============================================================================
alter table public.profiles enable row level security;
alter table public.patients enable row level security;
alter table public.scans    enable row level security;

-- helper : l'utilisateur courant est-il admin ?
create or replace function public.is_admin()
returns boolean language sql security definer stable set search_path = public as $$
  select exists (
    select 1 from public.profiles p
    where p.id = auth.uid() and p.role = 'admin'
  );
$$;

-- profiles : chacun lit tous les profils (annuaire), édite le sien ;
-- un admin peut tout modifier (changer les rôles).
drop policy if exists profiles_select on public.profiles;
create policy profiles_select on public.profiles
  for select using (auth.role() = 'authenticated');

drop policy if exists profiles_update_self on public.profiles;
create policy profiles_update_self on public.profiles
  for update using (id = auth.uid() or public.is_admin());

-- patients : lecture/insertion/mise à jour par tout authentifié ;
-- SUPPRESSION réservée aux admins (RLS séparées par opération = plus strict).
drop policy if exists patients_all on public.patients;
drop policy if exists patients_select on public.patients;
drop policy if exists patients_insert on public.patients;
drop policy if exists patients_update on public.patients;
drop policy if exists patients_delete on public.patients;
create policy patients_select on public.patients
  for select using (auth.role() = 'authenticated');
create policy patients_insert on public.patients
  for insert with check (auth.role() = 'authenticated');
create policy patients_update on public.patients
  for update using (auth.role() = 'authenticated');
create policy patients_delete on public.patients
  for delete using (public.is_admin());

-- scans : lecture/insertion/mise à jour par tout authentifié ; suppression admin.
drop policy if exists scans_all on public.scans;
drop policy if exists scans_select on public.scans;
drop policy if exists scans_insert on public.scans;
drop policy if exists scans_update on public.scans;
drop policy if exists scans_delete on public.scans;
create policy scans_select on public.scans
  for select using (auth.role() = 'authenticated');
create policy scans_insert on public.scans
  for insert with check (auth.role() = 'authenticated');
create policy scans_update on public.scans
  for update using (auth.role() = 'authenticated');
create policy scans_delete on public.scans
  for delete using (public.is_admin());

-- audit_log : chacun peut ajouter un événement ; SEUL un admin peut lire.
-- Personne ne peut modifier ou supprimer (journal inaltérable).
alter table public.audit_log enable row level security;
drop policy if exists audit_insert on public.audit_log;
drop policy if exists audit_select on public.audit_log;
create policy audit_insert on public.audit_log
  for insert with check (auth.role() = 'authenticated');
create policy audit_select on public.audit_log
  for select using (public.is_admin());

-- ============================================================================
--  Storage : bucket privé pour les radios
-- ============================================================================
insert into storage.buckets (id, name, public)
values ('radios', 'radios', false)
on conflict (id) do nothing;

drop policy if exists radios_rw on storage.objects;
create policy radios_rw on storage.objects
  for all using (bucket_id = 'radios' and auth.role() = 'authenticated')
  with check (bucket_id = 'radios' and auth.role() = 'authenticated');

-- ============================================================================
--  Astuce : pour te promouvoir admin après ta première inscription, exécute
--  (remplace l'email) :
--    update public.profiles set role = 'admin'
--    where id = (select id from auth.users where email = 'toi@exemple.fr');
-- ============================================================================

-- ============================================================================
--  V2 — MFA, CAPTCHA côté app, rôle patient, validation des professionnels
--  (idempotent : ré-exécutable sans risque sur un schéma V1 existant)
-- ============================================================================

-- --- Rôle 'patient' ----------------------------------------------------------
alter type user_role add value if not exists 'patient';

-- --- Colonnes MFA + validation sur les profils -------------------------------
alter table public.profiles add column if not exists mfa_secret text;
alter table public.profiles add column if not exists mfa_enabled boolean not null default false;
alter table public.profiles add column if not exists mfa_backup_codes jsonb not null default '[]'::jsonb;
alter table public.profiles add column if not exists approved boolean not null default false;
alter table public.profiles add column if not exists email text;

-- --- Lien dossier patient <-> compte utilisateur -----------------------------
alter table public.patients add column if not exists user_id uuid references public.profiles(id);
create index if not exists patients_user_idx on public.patients(user_id);

-- --- Création du profil à l'inscription : rôle demandé + validation ----------
-- Patients : actifs immédiatement. Professionnels : approved=false (un admin
-- valide depuis l'interface). Le rôle demandé vient des métadonnées du signup.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  req text := coalesce(new.raw_user_meta_data->>'requested_role', 'doctor');
begin
  if req not in ('doctor', 'patient') then req := 'doctor'; end if;
  insert into public.profiles (id, full_name, role, approved, email)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', ''),
    req::user_role,
    (req = 'patient'),          -- patient : actif ; doctor : à valider
    new.email
  )
  on conflict (id) do nothing;
  -- Dossier patient auto-créé et rattaché pour les comptes patients.
  if req = 'patient' then
    insert into public.patients (full_name, email, user_id)
    values (coalesce(new.raw_user_meta_data->>'full_name', ''), new.email, new.id);
  end if;
  return new;
end$$;

-- helper : rôle du compte courant
create or replace function public.current_role()
returns text language sql security definer stable set search_path = public as $$
  select role::text from public.profiles where id = auth.uid();
$$;

create or replace function public.is_staff()
returns boolean language sql security definer stable set search_path = public as $$
  select public.current_role() in ('doctor', 'admin');
$$;

-- ============================================================================
--  RLS V2 : les patients ne voient QUE leur dossier et leurs examens validés ;
--  seul le personnel (doctor/admin validé) lit et écrit l'ensemble.
-- ============================================================================

-- profiles : lecture par le personnel (annuaire) + soi-même ; MàJ de soi-même
-- (MFA, nom) ou par un admin (rôles, validation).
drop policy if exists profiles_select on public.profiles;
create policy profiles_select on public.profiles
  for select using (id = auth.uid() or public.is_staff());

drop policy if exists profiles_update_self on public.profiles;
create policy profiles_update_self on public.profiles
  for update using (id = auth.uid() or public.is_admin());

-- patients : personnel = tout ; patient = uniquement son dossier (lecture).
drop policy if exists patients_select on public.patients;
create policy patients_select on public.patients
  for select using (public.is_staff() or user_id = auth.uid());
drop policy if exists patients_insert on public.patients;
create policy patients_insert on public.patients
  for insert with check (public.is_staff());
drop policy if exists patients_update on public.patients;
create policy patients_update on public.patients
  for update using (public.is_staff());

-- scans : personnel = tout ; patient = lecture de SES examens VALIDÉS uniquement.
drop policy if exists scans_select on public.scans;
create policy scans_select on public.scans
  for select using (
    public.is_staff()
    or exists (
      select 1 from public.patients p
      where p.id = scans.patient_id
        and p.user_id = auth.uid()
        and scans.reviewed = true
    )
  );
drop policy if exists scans_insert on public.scans;
create policy scans_insert on public.scans
  for insert with check (public.is_staff());
drop policy if exists scans_update on public.scans;
create policy scans_update on public.scans
  for update using (public.is_staff());

-- storage : images réservées au personnel (les patients voient les résultats,
-- pas les fichiers bruts — remis en consultation).
drop policy if exists radios_rw on storage.objects;
create policy radios_rw on storage.objects
  for all using (bucket_id = 'radios' and public.is_staff())
  with check (bucket_id = 'radios' and public.is_staff());

-- ============================================================================
--  V3 — Médecin traitant : le patient choisit son médecin ; chaque médecin
--  ne voit que sa patientèle (l'admin voit tout). Idempotent.
-- ============================================================================
alter table public.patients add column if not exists doctor_id uuid
  references public.profiles(id) on delete set null;
create index if not exists patients_doctor_idx on public.patients(doctor_id);

-- Rattrapage : renseigne l'email des profils créés avant la V2 (nécessaire
-- au flux « mot de passe oublié »).
update public.profiles p set email = u.email
from auth.users u where u.id = p.id and p.email is null;

create or replace function public.is_admin_v3()
returns boolean language sql security definer stable set search_path = public as $$
  select public.current_role() = 'admin';
$$;

-- patients : admin = tout ; médecin = sa patientèle uniquement ;
-- patient = son propre dossier (lecture + choix du médecin traitant).
drop policy if exists patients_select on public.patients;
create policy patients_select on public.patients
  for select using (
    public.is_admin_v3() or doctor_id = auth.uid() or user_id = auth.uid()
  );
drop policy if exists patients_update on public.patients;
create policy patients_update on public.patients
  for update using (
    public.is_admin_v3() or doctor_id = auth.uid() or user_id = auth.uid()
  );

-- scans : admin = tout ; médecin = examens de sa patientèle ;
-- patient = ses examens VALIDÉS uniquement.
drop policy if exists scans_select on public.scans;
create policy scans_select on public.scans
  for select using (
    public.is_admin_v3()
    or exists (select 1 from public.patients p
               where p.id = scans.patient_id and p.doctor_id = auth.uid())
    or exists (select 1 from public.patients p
               where p.id = scans.patient_id and p.user_id = auth.uid()
                 and scans.reviewed = true)
  );

-- ============================================================================
--  V4 — Médecin traitant choisi À L'INSCRIPTION patient. Idempotent.
-- ============================================================================
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  req text := coalesce(new.raw_user_meta_data->>'requested_role', 'doctor');
  req_doc uuid;
begin
  if req not in ('doctor', 'patient') then req := 'doctor'; end if;
  insert into public.profiles (id, full_name, role, approved, email)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', ''),
    req::user_role,
    (req = 'patient'),
    new.email
  )
  on conflict (id) do nothing;
  if req = 'patient' then
    -- Médecin traitant demandé (vérifié : doit être un médecin/admin validé)
    begin
      req_doc := (new.raw_user_meta_data->>'requested_doctor')::uuid;
    exception when others then
      req_doc := null;
    end;
    if req_doc is not null and not exists (
        select 1 from public.profiles
        where id = req_doc and role in ('doctor','admin') and approved
    ) then
      req_doc := null;
    end if;
    insert into public.patients (full_name, email, user_id, doctor_id)
    values (coalesce(new.raw_user_meta_data->>'full_name', ''),
            new.email, new.id, req_doc);
  end if;
  return new;
end$$;

-- ============================================================================
--  V5 — TrueVision : le patient analyse lui-même sa radio et l'envoie à son
--  médecin traitant pour validation. Idempotent.
-- ============================================================================

-- scans : le patient peut INSÉRER un examen pour SON propre dossier.
drop policy if exists scans_insert on public.scans;
create policy scans_insert on public.scans
  for insert with check (
    public.is_staff()
    or exists (select 1 from public.patients p
               where p.id = patient_id and p.user_id = auth.uid())
  );

-- scans : le patient peut LIRE ses propres examens (y compris en attente,
-- pour le compteur « en attente de validation »). L'application ne montre
-- le RÉSULTAT que des examens validés ; pour un déploiement strict, exposer
-- plutôt une vue filtrant les colonnes de résultat des examens non validés.
drop policy if exists scans_select on public.scans;
create policy scans_select on public.scans
  for select using (
    public.is_admin_v3()
    or exists (select 1 from public.patients p
               where p.id = scans.patient_id and p.doctor_id = auth.uid())
    or exists (select 1 from public.patients p
               where p.id = scans.patient_id and p.user_id = auth.uid())
  );

-- storage : le personnel garde tous les droits ; le patient peut seulement
-- DÉPOSER un fichier (pas lire/modifier ceux des autres).
drop policy if exists radios_rw on storage.objects;
drop policy if exists radios_staff_all on storage.objects;
drop policy if exists radios_patient_upload on storage.objects;
create policy radios_staff_all on storage.objects
  for all using (bucket_id = 'radios' and public.is_staff())
  with check (bucket_id = 'radios' and public.is_staff());
create policy radios_patient_upload on storage.objects
  for insert with check (bucket_id = 'radios'
                         and auth.role() = 'authenticated');
