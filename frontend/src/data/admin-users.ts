import { AppUser } from "../types/index";

export const ADMIN_CREDENTIALS = { email: "admin@criiq.in", password: "Admin@2024" };

export const INITIAL_USERS: AppUser[] = [
  { id: 1, name: "Rahul Sharma",  email: "rahul@teamcricket.com",  password: "Coach@123",  role: "Coach",  status: "Active",    lastLogin: "2 min ago",   team: "India A", avatar: "RS" },
  { id: 2, name: "Priya Nair",    email: "priya@teamcricket.com",  password: "Player@456", role: "Player", status: "Active",    lastLogin: "30 min ago",  team: "India A", avatar: "PN" },
  { id: 3, name: "Vikram Singh",  email: "vikram@teamcricket.com", password: "Coach@789",  role: "Coach",  status: "Inactive",  lastLogin: "3 days ago",  team: "India B", avatar: "VS" },
  { id: 4, name: "Sunita Patel",  email: "sunita@teamcricket.com", password: "Player@321", role: "Player", status: "Active",    lastLogin: "5 min ago",   team: "India A", avatar: "SP" },
  { id: 5, name: "Rajan Mehta",   email: "rajan@teamcricket.com",  password: "Coach@654",  role: "Coach",  status: "Active",    lastLogin: "1 day ago",   team: "India B", avatar: "RM" },
  { id: 6, name: "Aisha Khan",    email: "aisha@teamcricket.com",  password: "Player@987", role: "Player", status: "Suspended", lastLogin: "2 weeks ago", team: "India A", avatar: "AK" },
  { id: 7, name: "Dev Malhotra",  email: "dev@teamcricket.com",    password: "Coach@111",  role: "Coach",  status: "Active",    lastLogin: "4 hr ago",    team: "India C", avatar: "DM" },
];
