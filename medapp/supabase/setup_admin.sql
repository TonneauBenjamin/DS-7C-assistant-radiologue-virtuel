-- ============================================================================
--  TrueVision — script de dépannage / initialisation admin (une seule fois)
--  SQL Editor > New query > coller > remplacer les 2 valeurs > Run.
--  Idempotent : ré-exécutable sans risque.
-- ============================================================================

-- ⚠️ REMPLACE ces deux valeurs avant d'exécuter :
--    TON_EMAIL        -> l'email de ton compte
--    TON_MOT_DE_PASSE -> un mot de passe (8+ car., majuscule, minuscule, chiffre)

create extension if not exists pgcrypto with schema extensions;

-- 1) Confirme tous les comptes en attente de confirmation d'email
update auth.users set email_confirmed_at = now()
where email_confirmed_at is null;

-- 2) (Re)définit le mot de passe du compte admin
update auth.users
set encrypted_password = extensions.crypt('TON_MOT_DE_PASSE', extensions.gen_salt('bf'))
where email = 'TON_EMAIL';

-- 3) Crée/répare le profil et le promeut admin validé
insert into public.profiles (id, full_name, role, approved, email)
select id, coalesce(raw_user_meta_data->>'full_name', 'Admin'), 'admin', true, email
from auth.users where email = 'TON_EMAIL'
on conflict (id) do update set role = 'admin', approved = true;

-- 4) Permet la suppression d'utilisateurs depuis le dashboard
--    (délie les références au lieu de bloquer)
alter table public.patients drop constraint if exists patients_created_by_fkey;
alter table public.patients add constraint patients_created_by_fkey
  foreign key (created_by) references public.profiles(id) on delete set null;
alter table public.patients drop constraint if exists patients_user_id_fkey;
alter table public.patients add constraint patients_user_id_fkey
  foreign key (user_id) references public.profiles(id) on delete set null;
alter table public.scans drop constraint if exists scans_uploaded_by_fkey;
alter table public.scans add constraint scans_uploaded_by_fkey
  foreign key (uploaded_by) references public.profiles(id) on delete set null;
alter table public.audit_log drop constraint if exists audit_log_actor_id_fkey;
alter table public.audit_log add constraint audit_log_actor_id_fkey
  foreign key (actor_id) references public.profiles(id) on delete set null;

-- Vérification finale : doit renvoyer ta ligne avec role=admin, approved=true,
-- et email_confirmed_at non nul.
select u.email, u.email_confirmed_at, p.role, p.approved
from auth.users u join public.profiles p on p.id = u.id;

-- 5) Rattrapage emails manquants dans profiles (requis pour
--    « mot de passe oublié » sur les comptes créés avant la V2)
update public.profiles p set email = u.email
from auth.users u where u.id = p.id and p.email is null;
