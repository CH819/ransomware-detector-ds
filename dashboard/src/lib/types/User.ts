export enum Role {
	USER = 'user',
	ADMIN = 'admin'
}

export interface User {
	email: string
	id: number
	role: Role
}
