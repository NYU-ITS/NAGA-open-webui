import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface FacilitiesRequest {
	sponsor: string; 
	form_data: Record<string, string>; 
	model: string; 
	web_search_enabled: boolean; 
	files?: any[]; 
}

export interface FacilitiesResponse {
	success: boolean;
	message: string;
	content: string;  // Formatted content for chat display
	sections: Record<string, string>;  // Keep sections for debugging
	sources: Array<{
		source: { id: string; name: string; url?: string };  // Match regular chat format
		document: string[];
		metadata: Array<{ source: string; name: string }>;
		distances?: number[];  // Relevance scores like regular chat
	}>;  // Sources in chat format
	error?: string;
}

export const generateFacilitiesResponse = async (
	token: string,
	request: FacilitiesRequest
): Promise<FacilitiesResponse> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/facilities/generate`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(request)
	})
		.then(async (res) => {
			if (!res.ok) {
				const errorData = await res.json();
				console.error('Facilities API error response:', errorData);
				throw errorData;
			}
			return res.json();
		})
		.catch((err) => {
			console.error('Facilities API fetch error:', err);
			error = err.detail ?? err.message ?? 'Server connection failed';
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};


export const getFacilitiesSections = async (
	token: string,
	sponsor: string
): Promise<{ success: boolean; sponsor: string; sections: string[] }> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/facilities/sections/${sponsor}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? 'Server connection failed';
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const downloadFacilitiesDocument = async (
	token: string,
	sections: Record<string, string>,
	format: 'pdf' | 'word',
	filename: string
): Promise<void> => {
	try {
		const response = await fetch(`${WEBUI_API_BASE_URL}/facilities/download`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify({
				sections: sections,
				format: format
			})
		});

		if (!response.ok) {
			const errorData = await response.json();
			throw new Error(errorData.detail || 'Failed to download document');
		}

		const blob = await response.blob();

		const url = window.URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		
		// Add timestamp to filename
		const now = new Date();
		const timestamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
		const extension = format === 'pdf' ? 'pdf' : 'docx';
		a.download = `${filename}_${timestamp}.${extension}`;

		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		window.URL.revokeObjectURL(url);
	} catch (error: any) {
		console.error('Error downloading facilities document:', error);
		throw error;
	}
};
