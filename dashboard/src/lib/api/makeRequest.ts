import { API_URL, AUTH_TOKEN_KEY } from '$lib/config/constants'

type APIError = {
	detail: string | Array<{ msg: string }>
}

export type MakeRequestProps = {
	/** API method as an URL path */
	path: string

	/** Query parameters */
	params?: Record<string, string>

	/** Fetch request options */
	requestOptions?: RequestInit
}

export type MakeRequestResult<T> = {
	response?: Response
	data: T
}

export default async <T = object>({
	path,
	params,
	requestOptions = {}
}: MakeRequestProps): Promise<MakeRequestResult<T>> => {
	const searchParams = new URLSearchParams(params)
	const searchString = searchParams.size > 0 ? '?' + searchParams.toString() : ''

	const headers: Record<string, string> = {
		...(requestOptions?.headers as Record<string, string>)
	}

	if (
		'body' in requestOptions &&
		!(requestOptions.body instanceof FormData) &&
		!headers['Content-Type']
	) {
		headers['Content-Type'] = 'application/json'
	}

	if (typeof window !== 'undefined') {
		const token = localStorage.getItem(AUTH_TOKEN_KEY)
		if (token) {
			headers['Authorization'] = `Bearer ${token}`
		}
	}

	try {
		const res = await fetch(API_URL + path + searchString, {
			method: requestOptions?.method || 'get',
			credentials: 'include',
			...requestOptions,
			headers
		})

		const text = await res.text()

		let data: (T & { detail?: never }) | APIError
		try {
			data = JSON.parse(text)
		} catch {
			throw new Error(`Failed to parse response: ${text}`)
		}

		if (!res.ok) {
			if (!('detail' in data)) throw new Error('Something went wrong')

			const detail = data.detail
			if (Array.isArray(detail)) throw new Error(detail.map((e) => e.msg).join(', '))
			throw new Error(detail)
		}

		return { data: data as T, response: res }
	} catch (e) {
		if (e && typeof e === 'object' && 'status' in e) throw e
		throw new Error((e as Error).message)
	}
}
