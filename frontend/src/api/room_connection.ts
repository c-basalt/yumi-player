import { requestJSON } from './common';

export interface RoomInfo {
    roomid: number;
    uid: number;
    short_id: number;
    uname: string | null;
}

export const getRoomConnectionStatus = async (): Promise<{connected: boolean}> => {
    return await requestJSON('/room_connection');
};

export const resetRoomConnection = async (): Promise<{connected: boolean}> => {
    return await requestJSON('/room_connection', {method: 'POST'});
};

